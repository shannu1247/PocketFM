"""
Code editor — uses LLM to generate file edits, then applies them.
Supports: full-file rewrite, targeted search-replace patches.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


SYSTEM_PROMPT = """You are an expert Go developer making targeted, minimal code changes.
Rules:
- Match the existing code style EXACTLY (tabs not spaces, same naming conventions)
- Make ONLY the changes needed to fix the issue — no refactoring, no cleanup
- Keep all existing comments and documentation
- Write idiomatic Go
- If adding tests, follow the exact same pattern as existing tests in the file
- NEVER change import paths or package names unless that is the fix"""


@dataclass
class EditResult:
    filepath: str
    original: str
    modified: str
    success: bool
    error: str = ""

    @property
    def changed(self) -> bool:
        return self.original != self.modified


class CodeEditor:
    def __init__(self, llm_client, repo_root: str):
        self.llm = llm_client
        self.repo_root = Path(repo_root)

    def edit_file(
        self,
        filepath: str,
        issue_description: str,
        fix_plan: str,
        current_content: str,
        related_context: str = "",
    ) -> EditResult:
        """Ask LLM to edit a file and return the result."""

        rel_path = filepath
        try:
            rel_path = str(Path(filepath).relative_to(self.repo_root))
        except Exception:
            pass

        is_test = filepath.endswith("_test.go")
        file_type = "test file" if is_test else "Go source file"

        context_section = ""
        if related_context:
            context_section = f"\n## Related Context (for reference only, do not modify)\n```go\n{related_context[:2000]}\n```\n"

        prompt = f"""
You need to modify this {file_type} to fix the following issue.

## Issue
{issue_description}

## Fix Plan for This File
{fix_plan}
{context_section}
## Current File: {rel_path}
```go
{current_content}
```

## Instructions
1. Analyze what specific change is needed in THIS file
2. Make ONLY the minimal change required
3. Return the COMPLETE modified file content

Respond with ONLY the modified Go code. No explanation, no markdown fences, no preamble.
Start your response directly with `package ...`
"""

        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        # Clean up response (remove accidental markdown fences)
        modified = self._clean_go_response(response)

        # Sanity checks
        if not modified.strip():
            return EditResult(
                filepath=filepath,
                original=current_content,
                modified=current_content,
                success=False,
                error="LLM returned empty content",
            )

        if not self._looks_like_go(modified):
            return EditResult(
                filepath=filepath,
                original=current_content,
                modified=current_content,
                success=False,
                error=f"LLM response doesn't look like Go code: {modified[:100]}",
            )

        return EditResult(
            filepath=filepath,
            original=current_content,
            modified=modified,
            success=True,
        )

    def _clean_go_response(self, text: str) -> str:
        """Strip markdown fences and preamble from LLM response."""
        text = text.strip()

        # Remove ```go ... ``` or ``` ... ``` blocks
        fence_match = re.search(r"```(?:go)?\n([\s\S]+?)```", text)
        if fence_match:
            return fence_match.group(1).strip()

        # Remove any leading non-Go text before 'package'
        pkg_idx = text.find("package ")
        if pkg_idx > 0:
            text = text[pkg_idx:]

        return text

    def _looks_like_go(self, content: str) -> bool:
        """Basic check that content looks like Go source code."""
        content = content.strip()
        return (
            content.startswith("package ") or
            "package " in content[:200]
        )

    def retry_edit(
        self,
        filepath: str,
        issue_description: str,
        fix_plan: str,
        current_content: str,
        error_output: str,
        previous_attempt: str,
    ) -> EditResult:
        """Retry edit with validation errors fed back to LLM."""
        rel_path = filepath
        try:
            rel_path = str(Path(filepath).relative_to(self.repo_root))
        except Exception:
            pass

        prompt = f"""
Your previous edit to {rel_path} caused errors. Please fix them.

## Issue Being Fixed
{issue_description}

## Fix Plan
{fix_plan}

## Your Previous (Broken) Edit
```go
{previous_attempt[:3000]}
```

## Errors from Go Compiler/Tester
```
{error_output[:2000]}
```

## Original File (before your edit)
```go
{current_content[:3000]}
```

Fix the errors and return the COMPLETE corrected file.
Respond with ONLY valid Go code starting with `package ...`
"""
        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        modified = self._clean_go_response(response)
        success = self._looks_like_go(modified) and bool(modified.strip())

        return EditResult(
            filepath=filepath,
            original=current_content,
            modified=modified,
            success=success,
            error="" if success else "Retry also produced invalid Go code",
        )
