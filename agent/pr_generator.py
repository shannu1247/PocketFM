"""
PR Generator — creates a structured pull request title and body.
"""

from dataclasses import dataclass
from typing import List


SYSTEM_PROMPT = """You are writing a pull request for an open-source Go project.
Write in a professional, concise style matching typical open-source PR conventions.
Be specific about WHAT changed and WHY. Don't be vague."""


@dataclass
class PRSummary:
    title: str
    body: str

    def full_text(self) -> str:
        return f"# {self.title}\n\n{self.body}"


class PRGenerator:
    def __init__(self, llm_client):
        self.llm = llm_client

    def generate(
        self,
        issue,
        fix_plan,
        diff: str,
        validation_passed: bool,
        changed_files: List[str],
    ) -> PRSummary:
        print("   📝 Generating PR summary...")

        diff_preview = diff[:3000] if diff else "(no diff available)"
        files_list = "\n".join(f"- `{f}`" for f in changed_files)

        prompt = f"""
Generate a pull request for this fix.

## Issue
Title: {issue.title}
URL: {issue.url}
Description: {issue.body[:500]}

## Fix Summary
{fix_plan.summary}

Approach: {fix_plan.approach[:500]}

## Changed Files
{files_list}

## Diff Preview
```diff
{diff_preview}
```

## Validation
{'✅ All Go checks passed (build, vet, tests)' if validation_passed else '⚠️ Validation had issues (see details)'}

---

Write a pull request with this exact structure:

TITLE: <concise title starting with verb, e.g. "Fix", "Add", "Handle", "Correct">

BODY:
## Problem
[Describe the issue being fixed — 2-3 sentences]

## Solution
[Describe what was changed and why — 3-5 sentences]

## Changes
[Bullet list of specific changes made]

## Testing
[How this was tested / what tests were added or modified]

## Related Issues
Fixes #{issue.number}
"""

        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        return self._parse_pr(response, issue)

    def _parse_pr(self, text: str, issue) -> PRSummary:
        """Parse TITLE: / BODY: from LLM response."""
        lines = text.strip().splitlines()

        title = ""
        body_lines = []
        in_body = False

        for line in lines:
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
            elif line.strip() == "BODY:":
                in_body = True
            elif in_body:
                body_lines.append(line)

        if not title:
            # Fallback: use first line
            title = lines[0].replace("#", "").strip() if lines else f"Fix issue #{issue.number}"

        if not body_lines:
            body_lines = lines[1:]

        body = "\n".join(body_lines).strip()
        if not body:
            body = text.strip()

        return PRSummary(title=title, body=body)
