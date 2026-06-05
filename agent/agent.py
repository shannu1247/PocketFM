"""
GoContributorAgent — the main agentic loop.

Flow:
  1. Fetch issue from GitHub
  2. Clone / update repository
  3. Build repo map (file tree + Go symbols)
  4. Pass 1: Identify relevant files (LLM)
  5. Read file contents + search for context
  6. Pass 2: Plan the fix (LLM)
  7. Edit each file (LLM)
  8. Apply edits to disk
  9. Run validation (go build, vet, test)
  10. Retry on failure (up to 2 times)
  11. Generate PR summary (LLM)
  12. Save diff + summary to output dir
"""

import os
import json
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from tools.github_tool import GitHubTool
from tools.repo_tool import RepoTool
from tools.search_tool import SearchTool
from tools.validation_tool import ValidationTool
from agent.planner import Planner
from agent.code_editor import CodeEditor
from agent.pr_generator import PRGenerator


@dataclass
class AgentResult:
    success: bool
    diff_path: str = ""
    pr_summary_path: str = ""
    pr_summary: str = ""
    log_path: str = ""
    error: str = ""


class GoContributorAgent:
    MAX_RETRIES = 2

    def __init__(self, config):
        self.config = config
        self.llm = config.get_llm_client()
        self.github = GitHubTool(token=config.github_token)
        self.repo_tool = RepoTool(workspace_dir=config.workspace_dir)
        self.planner = Planner(self.llm)
        self.pr_generator = PRGenerator(self.llm)
        self._log_lines: List[str] = []

    def _log(self, msg: str):
        print(msg)
        self._log_lines.append(msg)

    def run(self, issue_url: str) -> AgentResult:
        self._log_lines = []
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ── Step 1: Fetch Issue ──────────────────────────────────────
            self._log("\n[1/9] 📥 Fetching issue...")
            issue = self.github.fetch_issue_from_url(issue_url)
            self._log(f"      Issue #{issue.number}: {issue.title}")
            self._log(f"      State: {issue.state} | Labels: {issue.labels}")
            if issue.linked_prs:
                self._log(f"      Linked PRs: {[p['number'] for p in issue.linked_prs]}")

            # ── Step 2: Clone Repo ───────────────────────────────────────
            self._log("\n[2/9] 📦 Cloning repository...")
            repo_dir = self.repo_tool.clone_or_update(issue.repo_owner, issue.repo_name)

            # ── Step 3: Build Repo Map ───────────────────────────────────
            self._log("\n[3/9] 🗺️  Building repository map...")
            repo_map = self.repo_tool.build_repo_map(repo_dir)
            self._log(f"      {len(repo_map.go_files)} Go files, {len(repo_map.symbols)} symbols")
            self._log(f"      Packages: {list(repo_map.packages.keys())[:10]}")

            # ── Step 4: Identify Files ───────────────────────────────────
            self._log("\n[4/9] 🎯 Identifying relevant files (LLM Pass 1)...")
            if self.config.dry_run:
                self._log("      [DRY RUN] Skipping LLM calls")
                return AgentResult(success=True, error="dry-run mode")

            file_plans = self.planner.identify_files(issue, repo_map)
            if not file_plans:
                return AgentResult(success=False, error="Could not identify relevant files")

            self._log(f"      Found {len(file_plans)} relevant files:")
            for fp in file_plans:
                self._log(f"      [{fp.action}] {fp.filepath} — {fp.reason[:80]}")

            # ── Step 5: Read Files + Search ──────────────────────────────
            self._log("\n[5/9] 📖 Reading files and gathering context...")
            search_tool = SearchTool(str(repo_dir))
            file_contents = {}

            for fp in file_plans:
                full_path = repo_dir / fp.filepath
                if full_path.exists():
                    content = self.repo_tool.read_file(str(full_path))
                    file_contents[fp.filepath] = content
                    self._log(f"      Read: {fp.filepath} ({len(content)} chars)")
                else:
                    # Try searching for the file
                    matches = search_tool.search(
                        Path(fp.filepath).name,
                        file_pattern="*.go",
                        max_results=1,
                    )
                    if matches:
                        actual_path = matches[0].file
                        rel = str(Path(actual_path).relative_to(repo_dir))
                        content = self.repo_tool.read_file(actual_path)
                        file_contents[rel] = content
                        self._log(f"      Found via search: {rel}")
                    else:
                        self._log(f"      ⚠️  File not found: {fp.filepath}")

            # Search for additional context based on issue keywords
            keywords = self._extract_keywords(issue)
            for kw in keywords[:3]:
                results = search_tool.search(kw, max_results=5)
                if results and self.config.verbose:
                    self._log(f"      Search '{kw}': {len(results)} results")

            # ── Step 6: Plan Fix ─────────────────────────────────────────
            self._log("\n[6/9] 📋 Planning the fix (LLM Pass 2)...")
            fix_plan = self.planner.plan_fix(issue, file_contents)
            self._log(f"      Summary: {fix_plan.summary}")
            self._log(f"      Approach: {fix_plan.approach[:200]}...")

            # ── Step 7 & 8: Edit Files ───────────────────────────────────
            self._log("\n[7/9] ✏️  Editing files...")
            editor = CodeEditor(self.llm, repo_root=str(repo_dir))
            edit_results = []

            files_to_modify = [fp for fp in file_plans if fp.action in ("modify", "create")]

            for fp in files_to_modify:
                full_path = repo_dir / fp.filepath
                current = file_contents.get(fp.filepath, "")

                if not current and fp.action != "create":
                    self._log(f"      ⚠️  Skipping {fp.filepath} — content not available")
                    continue

                self._log(f"      Editing: {fp.filepath}")

                # Get related context (other modified files for reference)
                related = "\n\n".join(
                    f"// {other_path}\n{content[:1000]}"
                    for other_path, content in file_contents.items()
                    if other_path != fp.filepath
                )[:2000]

                result = editor.edit_file(
                    filepath=str(full_path),
                    issue_description=issue.full_text[:1500],
                    fix_plan=f"{fix_plan.approach}\n\nFor this file: {fp.reason}",
                    current_content=current,
                    related_context=related,
                )
                edit_results.append(result)

                if result.success and result.changed:
                    self.repo_tool.write_file(str(full_path), result.modified)
                    self._log(f"      ✅ {fp.filepath} — written")
                elif not result.changed:
                    self._log(f"      ℹ️  {fp.filepath} — no changes needed")
                else:
                    self._log(f"      ❌ {fp.filepath} — edit failed: {result.error}")

            changed_files = [
                str(repo_dir / fp.filepath)
                for fp, r in zip(files_to_modify, edit_results)
                if r.success and r.changed
            ]

            # ── Step 9: Validate ─────────────────────────────────────────
            self._log("\n[8/9] 🔧 Running validation...")
            validation_tool = ValidationTool(str(repo_dir))

            if not validation_tool.check_go_installed():
                self._log("      ⚠️  Go not installed — skipping validation")
                validation_report = None
                validation_passed = False
            else:
                validation_report = validation_tool.run_full_validation(changed_files)
                validation_passed = validation_report.all_passed
                self._log(validation_report.summary())

                # Retry on failure
                if not validation_passed and edit_results:
                    self._log("\n      🔄 Retrying failed edits with error feedback...")
                    for attempt in range(self.MAX_RETRIES):
                        self._log(f"      Retry {attempt + 1}/{self.MAX_RETRIES}...")
                        error_text = validation_report.error_text()

                        for i, (fp, r) in enumerate(zip(files_to_modify, edit_results)):
                            if not r.changed:
                                continue
                            full_path = repo_dir / fp.filepath
                            retry_result = editor.retry_edit(
                                filepath=str(full_path),
                                issue_description=issue.full_text[:1000],
                                fix_plan=fp.reason,
                                current_content=r.original,
                                error_output=error_text,
                                previous_attempt=r.modified,
                            )
                            if retry_result.success and retry_result.changed:
                                self.repo_tool.write_file(str(full_path), retry_result.modified)
                                edit_results[i] = retry_result
                                self._log(f"      ✅ Retry ok: {fp.filepath}")

                        validation_report = validation_tool.run_full_validation(changed_files)
                        validation_passed = validation_report.all_passed
                        if validation_passed:
                            self._log("      ✅ Validation passed after retry!")
                            break

            # ── Step 10: Get Diff ────────────────────────────────────────
            diff = self.repo_tool.get_git_diff(repo_dir)

            # ── Step 11: Generate PR ─────────────────────────────────────
            self._log("\n[9/9] 📋 Generating PR summary...")
            changed_rel = [
                str(Path(f).relative_to(repo_dir))
                for f in changed_files
            ]
            pr_summary = self.pr_generator.generate(
                issue=issue,
                fix_plan=fix_plan,
                diff=diff,
                validation_passed=validation_passed if validation_report else False,
                changed_files=changed_rel,
            )
            self._log(f"      PR Title: {pr_summary.title}")

            # ── Save Outputs ─────────────────────────────────────────────
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = f"issue_{issue.number}_{timestamp}"

            diff_path = output_dir / f"{prefix}.diff"
            diff_path.write_text(diff or "(no changes made)", encoding="utf-8")

            pr_path = output_dir / f"{prefix}_pr_summary.md"
            pr_path.write_text(pr_summary.full_text(), encoding="utf-8")

            plan_path = output_dir / f"{prefix}_plan.json"
            plan_path.write_text(json.dumps({
                "issue": {"number": issue.number, "title": issue.title, "url": issue.url},
                "fix_summary": fix_plan.summary,
                "approach": fix_plan.approach,
                "test_strategy": fix_plan.test_strategy,
                "risks": fix_plan.risks,
                "changed_files": changed_rel,
                "validation_passed": validation_passed if validation_report else None,
            }, indent=2), encoding="utf-8")

            log_path = output_dir / f"{prefix}_log.txt"
            log_path.write_text("\n".join(self._log_lines), encoding="utf-8")

            self._log(f"\n   Outputs saved to: {output_dir}/")

            return AgentResult(
                success=True,
                diff_path=str(diff_path),
                pr_summary_path=str(pr_path),
                pr_summary=pr_summary.full_text(),
                log_path=str(log_path),
            )

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self._log(f"\n❌ Agent error: {error_msg}")

            log_path = output_dir / "error_log.txt"
            log_path.write_text("\n".join(self._log_lines) + "\n\n" + error_msg, encoding="utf-8")

            return AgentResult(success=False, error=str(e), log_path=str(log_path))

    def _extract_keywords(self, issue) -> List[str]:
        """Extract searchable keywords from issue text."""
        import re
        text = f"{issue.title} {issue.body}"
        # Extract Go identifiers (CamelCase, snake_case with caps)
        identifiers = re.findall(r'\b[A-Z][a-zA-Z0-9]+\b', text)
        # Extract backtick-quoted terms
        backtick = re.findall(r'`([^`]+)`', text)
        keywords = list(dict.fromkeys(backtick + identifiers))
        return [k for k in keywords if len(k) > 2][:10]
