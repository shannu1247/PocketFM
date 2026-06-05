"""
Validation tool — run Go build, test, vet, and fmt checks.
"""

import subprocess
import os
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path


@dataclass
class ValidationResult:
    passed: bool
    command: str
    stdout: str
    stderr: str
    return_code: int

    def summary(self) -> str:
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        lines = [f"{status}: {self.command}"]
        if self.stderr and not self.passed:
            lines.append(f"STDERR:\n{self.stderr[:2000]}")
        if self.stdout and not self.passed:
            lines.append(f"STDOUT:\n{self.stdout[:1000]}")
        return "\n".join(lines)


@dataclass
class ValidationReport:
    results: List[ValidationResult]

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed(self) -> List[ValidationResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        lines = ["== Validation Report =="]
        for r in self.results:
            lines.append(r.summary())
        if self.all_passed:
            lines.append("\n✅ All checks passed!")
        else:
            lines.append(f"\n❌ {len(self.failed)} check(s) failed.")
        return "\n".join(lines)

    def error_text(self) -> str:
        """Return combined error output for failed checks."""
        parts = []
        for r in self.failed:
            parts.append(f"[{r.command}]\n{r.stderr}\n{r.stdout}")
        return "\n\n".join(parts)


class ValidationTool:
    def __init__(self, repo_dir: str):
        self.repo_dir = Path(repo_dir)

    def _run(self, cmd: List[str], timeout: int = 120) -> ValidationResult:
        cmd_str = " ".join(cmd)
        print(f"   🔧 Running: {cmd_str}")
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "GOFLAGS": "-mod=mod", "GO111MODULE": "on"},
            )
            passed = proc.returncode == 0
            return ValidationResult(
                passed=passed,
                command=cmd_str,
                stdout=proc.stdout,
                stderr=proc.stderr,
                return_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                command=cmd_str,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1,
            )
        except FileNotFoundError:
            return ValidationResult(
                passed=False,
                command=cmd_str,
                stdout="",
                stderr="Command not found. Is Go installed and in PATH?",
                return_code=-1,
            )

    def go_build(self) -> ValidationResult:
        return self._run(["go", "build", "./..."])

    def go_vet(self) -> ValidationResult:
        return self._run(["go", "vet", "./..."])

    def go_fmt_check(self) -> ValidationResult:
        """Check that files are properly formatted (doesn't modify)."""
        result = self._run(["gofmt", "-l", "."])
        # gofmt -l prints files that need formatting; empty = all good
        if result.passed and result.stdout.strip():
            result.passed = False
            result.stderr = f"Files need formatting:\n{result.stdout}"
        return result

    def go_test(self, pkg: str = "./...", timeout: str = "60s") -> ValidationResult:
        return self._run(["go", "test", f"-timeout={timeout}", "-v", pkg], timeout=120)

    def go_test_specific(self, test_file: str) -> ValidationResult:
        """Run tests only in the directory of a specific test file."""
        pkg_dir = str(Path(test_file).parent.relative_to(self.repo_dir))
        if pkg_dir == ".":
            pkg = "."
        else:
            pkg = "./" + pkg_dir
        return self._run(["go", "test", "-timeout=60s", "-v", pkg])

    def run_full_validation(self, changed_files: List[str] = None) -> ValidationReport:
        """Run the standard suite: build → vet → test relevant packages."""
        results = []

        # 1. Build
        results.append(self.go_build())

        # 2. Vet
        if results[-1].passed:
            results.append(self.go_vet())

        # 3. Test
        if results[-1].passed:
            if changed_files:
                # Run tests only for packages of changed files
                pkgs = set()
                for f in changed_files:
                    try:
                        rel = str(Path(f).relative_to(self.repo_dir))
                        pkg_dir = str(Path(rel).parent)
                        pkgs.add("./" + pkg_dir if pkg_dir != "." else ".")
                    except Exception:
                        pkgs.add("./...")
                for pkg in pkgs:
                    results.append(self.go_test(pkg))
            else:
                results.append(self.go_test("./..."))

        return ValidationReport(results=results)

    def check_go_installed(self) -> bool:
        try:
            r = subprocess.run(["go", "version"], capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False
