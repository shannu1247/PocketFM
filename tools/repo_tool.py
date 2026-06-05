"""
Repo tool — clone repository, build file tree, extract Go symbols via AST.
Uses only stdlib + git CLI (no extra deps needed).
"""

import os
import re
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class GoSymbol:
    kind: str        # func | type | interface | const | var
    name: str
    file: str
    line: int
    signature: str   # full declaration line


@dataclass
class RepoMap:
    root: str
    go_files: List[str]
    symbols: List[GoSymbol]
    packages: Dict[str, List[str]]   # package → [files]
    test_files: List[str]
    readme: str

    def summary(self) -> str:
        lines = [
            f"Repository root: {self.root}",
            f"Go files: {len(self.go_files)} ({len(self.test_files)} test files)",
            f"Packages: {', '.join(sorted(self.packages.keys()))}",
            "",
            "== File Tree (non-vendor) ==",
        ]
        for f in sorted(self.go_files)[:80]:
            rel = os.path.relpath(f, self.root)
            lines.append(f"  {rel}")
        if len(self.go_files) > 80:
            lines.append(f"  ... and {len(self.go_files)-80} more")
        return "\n".join(lines)

    def symbols_for_file(self, filepath: str) -> List[GoSymbol]:
        return [s for s in self.symbols if s.file == filepath]

    def find_symbols(self, query: str) -> List[GoSymbol]:
        q = query.lower()
        return [s for s in self.symbols if q in s.name.lower()]


class RepoTool:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def clone_or_update(self, owner: str, repo: str, branch: str = "") -> Path:
        repo_dir = self.workspace_dir / f"{owner}__{repo}"

        if repo_dir.exists():
            print(f"   📂 Repo already cloned at {repo_dir}, pulling latest...")
            try:
                subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=repo_dir, capture_output=True, timeout=60
                )
            except Exception:
                pass  # If pull fails, use existing
        else:
            print(f"   📦 Cloning {owner}/{repo}...")
            url = f"https://github.com/{owner}/{repo}.git"
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(repo_dir)],
                check=True, capture_output=True, timeout=300
            )

        if branch:
            subprocess.run(
                ["git", "checkout", branch],
                cwd=repo_dir, capture_output=True, timeout=30
            )

        # Create a working branch for our changes
        branch_name = "ai-contributor-fix"
        subprocess.run(
            ["git", "checkout", "-B", branch_name],
            cwd=repo_dir, capture_output=True, timeout=10
        )

        print(f"   ✅ Repo ready at {repo_dir}")
        return repo_dir

    def build_repo_map(self, repo_dir: Path) -> RepoMap:
        print("   🗺️  Building repository map...")
        go_files = []
        test_files = []
        packages: Dict[str, List[str]] = {}
        symbols: List[GoSymbol] = []

        # Walk all .go files (skip vendor, .git, testdata)
        skip_dirs = {".git", "vendor", "testdata", "node_modules", ".github"}
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if not fname.endswith(".go"):
                    continue
                fpath = os.path.join(root, fname)
                go_files.append(fpath)
                if fname.endswith("_test.go"):
                    test_files.append(fpath)

                # Detect package
                pkg = self._detect_package(fpath)
                if pkg:
                    packages.setdefault(pkg, []).append(fpath)

                # Extract symbols
                file_symbols = self._extract_symbols(fpath)
                symbols.extend(file_symbols)

        # Read README
        readme = ""
        for name in ["README.md", "README.rst", "README"]:
            readme_path = repo_dir / name
            if readme_path.exists():
                readme = readme_path.read_text(errors="replace")[:3000]
                break

        return RepoMap(
            root=str(repo_dir),
            go_files=go_files,
            symbols=symbols,
            packages=packages,
            test_files=test_files,
            readme=readme,
        )

    def _detect_package(self, filepath: str) -> Optional[str]:
        try:
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("package "):
                        return line.split()[1]
                    if line and not line.startswith("//"):
                        break
        except Exception:
            pass
        return None

    def _extract_symbols(self, filepath: str) -> List[GoSymbol]:
        """
        Lightweight Go symbol extractor using regex.
        Captures: func, type, interface, const, var declarations.
        """
        symbols = []
        patterns = [
            ("func",      re.compile(r"^func\s+(\(.*?\)\s+)?(\w+)\s*\(")),
            ("type",      re.compile(r"^type\s+(\w+)\s+(struct|interface)")),
            ("interface", re.compile(r"^type\s+(\w+)\s+interface")),
            ("const",     re.compile(r"^const\s+(\w+)\s")),
            ("var",       re.compile(r"^var\s+(\w+)\s")),
        ]

        try:
            with open(filepath, "r", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    stripped = line.strip()
                    for kind, pat in patterns:
                        m = pat.match(stripped)
                        if m:
                            # Extract name
                            if kind == "func":
                                name = m.group(2) if m.group(2) else m.group(1)
                            else:
                                name = m.group(1)
                            symbols.append(GoSymbol(
                                kind=kind,
                                name=name,
                                file=filepath,
                                line=lineno,
                                signature=stripped[:120],
                            ))
                            break
        except Exception:
            pass
        return symbols

    def read_file(self, filepath: str) -> str:
        try:
            return Path(filepath).read_text(errors="replace")
        except Exception as e:
            return f"ERROR reading file: {e}"

    def write_file(self, filepath: str, content: str):
        Path(filepath).write_text(content)

    def get_git_diff(self, repo_dir: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_dir,
                capture_output=True, text=True, timeout=30
            )
            return result.stdout
        except Exception as e:
            return f"ERROR getting diff: {e}"
