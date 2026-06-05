"""
Search tool — symbol and text search across Go repositories.
Uses ripgrep if available, falls back to pure Python grep.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import List
from dataclasses import dataclass


@dataclass
class SearchResult:
    file: str
    line: int
    text: str
    context_before: List[str]
    context_after: List[str]

    def format(self, repo_root: str = "") -> str:
        rel = os.path.relpath(self.file, repo_root) if repo_root else self.file
        lines = []
        for i, c in enumerate(self.context_before):
            lines.append(f"  {self.line - len(self.context_before) + i}: {c}")
        lines.append(f"→ {self.line}: {self.text}")
        for i, c in enumerate(self.context_after):
            lines.append(f"  {self.line + 1 + i}: {c}")
        return f"[{rel}]\n" + "\n".join(lines)


class SearchTool:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self._has_rg = self._check_rg()

    def _check_rg(self) -> bool:
        try:
            subprocess.run(["rg", "--version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def search(
        self,
        query: str,
        file_pattern: str = "*.go",
        context_lines: int = 3,
        max_results: int = 20,
        case_sensitive: bool = False,
    ) -> List[SearchResult]:
        """Search for a text pattern across Go files."""
        if self._has_rg:
            return self._rg_search(query, file_pattern, context_lines, max_results, case_sensitive)
        return self._python_search(query, file_pattern, context_lines, max_results, case_sensitive)

    def _rg_search(self, query, file_pattern, context_lines, max_results, case_sensitive) -> List[SearchResult]:
        cmd = [
            "rg",
            "--glob", file_pattern,
            "--glob", "!vendor/**",
            "--glob", "!testdata/**",
            "-n",  # line numbers
            f"--context={context_lines}",
            "--json",
        ]
        if not case_sensitive:
            cmd.append("-i")
        cmd += [query, self.repo_root]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            results = []
            current_match = None
            before_ctx = []
            after_ctx = []

            for line in proc.stdout.splitlines():
                try:
                    obj = __import__("json").loads(line)
                except Exception:
                    continue

                t = obj.get("type")
                if t == "begin":
                    before_ctx = []
                    after_ctx = []
                    current_match = None
                elif t == "context":
                    data = obj.get("data", {})
                    text = data.get("lines", {}).get("text", "").rstrip("\n")
                    if current_match is None:
                        before_ctx.append(text)
                    else:
                        after_ctx.append(text)
                elif t == "match":
                    data = obj.get("data", {})
                    text = data.get("lines", {}).get("text", "").rstrip("\n")
                    lineno = data.get("line_number", 0)
                    filepath = data.get("path", {}).get("text", "")
                    current_match = SearchResult(
                        file=filepath,
                        line=lineno,
                        text=text,
                        context_before=list(before_ctx),
                        context_after=[],
                    )
                    results.append(current_match)
                    before_ctx = []
                    if len(results) >= max_results:
                        break
                elif t == "end" and current_match:
                    current_match.context_after = list(after_ctx)
                    after_ctx = []

            return results
        except Exception as e:
            print(f"   ⚠️  ripgrep failed ({e}), falling back to Python search")
            return self._python_search(query, file_pattern, context_lines, max_results, case_sensitive)

    def _python_search(self, query, file_pattern, context_lines, max_results, case_sensitive) -> List[SearchResult]:
        import fnmatch
        results = []
        skip_dirs = {".git", "vendor", "testdata"}
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            pattern = re.compile(re.escape(query), flags)
        except re.error:
            pattern = re.compile(query, flags)

        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if not fnmatch.fnmatch(fname, file_pattern):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", errors="replace") as f:
                        file_lines = f.readlines()
                except Exception:
                    continue

                for i, line in enumerate(file_lines):
                    if pattern.search(line):
                        before = [
                            file_lines[j].rstrip("\n")
                            for j in range(max(0, i - context_lines), i)
                        ]
                        after = [
                            file_lines[j].rstrip("\n")
                            for j in range(i + 1, min(len(file_lines), i + 1 + context_lines))
                        ]
                        results.append(SearchResult(
                            file=fpath,
                            line=i + 1,
                            text=line.rstrip("\n"),
                            context_before=before,
                            context_after=after,
                        ))
                        if len(results) >= max_results:
                            return results
        return results

    def find_test_for_file(self, filepath: str) -> str:
        """Find the corresponding _test.go file for a given .go file."""
        p = Path(filepath)
        test_path = p.parent / (p.stem + "_test.go")
        if test_path.exists():
            return str(test_path)
        return ""

    def format_results(self, results: List[SearchResult]) -> str:
        if not results:
            return "(no results found)"
        parts = []
        for r in results:
            parts.append(r.format(self.repo_root))
        return "\n\n".join(parts)
