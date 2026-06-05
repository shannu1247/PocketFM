"""
Planner — two-pass LLM planning:
  Pass 1: Given issue + repo map → identify relevant files
  Pass 2: Given files + context → generate concrete fix plan
"""

import json
import re
from dataclasses import dataclass, field
from typing import List
from pathlib import Path


@dataclass
class FilePlan:
    filepath: str
    reason: str
    action: str   # "modify" | "create" | "read_only"


@dataclass
class FixPlan:
    summary: str
    files: List[FilePlan]
    approach: str
    test_strategy: str
    risks: str


SYSTEM_PROMPT = """You are an expert Go developer helping contribute to open-source projects.
You write clean, idiomatic Go code that matches existing project conventions.
You are precise, careful, and always follow the existing code style.
When unsure, you prefer minimal, targeted changes over large rewrites."""


def _extract_json(text: str) -> dict:
    """Try to parse JSON from LLM response, handling markdown code blocks."""
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\n?", "", text).strip()
    text = text.strip("`").strip()

    # Find first { ... } block
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")
    # Find matching closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i+1])
    raise ValueError("Could not find complete JSON object")


class Planner:
    def __init__(self, llm_client):
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Pass 1: File identification
    # ------------------------------------------------------------------
    def identify_files(self, issue, repo_map) -> List[FilePlan]:
        print("   🎯 Pass 1: Identifying relevant files...")

        # Build a condensed symbol index for the prompt
        symbol_lines = []
        for sym in repo_map.symbols[:300]:  # Limit to avoid token overflow
            rel = Path(sym.file).relative_to(repo_map.root)
            symbol_lines.append(f"  {rel}:{sym.line}  [{sym.kind}] {sym.name}")
        symbol_index = "\n".join(symbol_lines)

        file_list = "\n".join(
            "  " + str(Path(f).relative_to(repo_map.root))
            for f in sorted(repo_map.go_files)[:100]
        )

        prompt = f"""
You are analyzing a GitHub issue to identify which files need to be changed.

## Issue
{issue.full_text}

## Repository File Tree
{file_list}

## Symbol Index (file:line [kind] name)
{symbol_index}

## Task
Identify the files that need to be READ or MODIFIED to fix this issue.
Think step by step:
1. What is the core problem described in the issue?
2. What Go types, functions, or packages are mentioned?
3. Which files are most likely to need changes?
4. Which test files are relevant?

Respond ONLY with a valid JSON object like this:
{{
  "reasoning": "Step-by-step explanation of which files are relevant and why",
  "files": [
    {{
      "filepath": "relative/path/to/file.go",
      "reason": "Why this file is relevant",
      "action": "modify"
    }},
    {{
      "filepath": "relative/path/to/file_test.go",
      "reason": "Test file for the modified code",
      "action": "modify"
    }}
  ]
}}

Actions: "modify" = needs changes, "read_only" = needed for context only, "create" = new file.
Include at most 8 files. Prioritize the most relevant ones.
"""
        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        try:
            data = _extract_json(response)
            print(f"   📝 Reasoning: {data.get('reasoning', '')[:200]}...")
            files = []
            for f in data.get("files", []):
                files.append(FilePlan(
                    filepath=f.get("filepath", ""),
                    reason=f.get("reason", ""),
                    action=f.get("action", "modify"),
                ))
            return files
        except Exception as e:
            print(f"   ⚠️  Could not parse file plan JSON: {e}")
            print(f"   Raw response: {response[:500]}")
            return []

    # ------------------------------------------------------------------
    # Pass 2: Fix planning
    # ------------------------------------------------------------------
    def plan_fix(self, issue, file_contents: dict) -> FixPlan:
        print("   📋 Pass 2: Planning the fix...")

        files_section = ""
        for filepath, content in file_contents.items():
            files_section += f"\n\n### {filepath}\n```go\n{content[:3000]}\n```"
            if len(content) > 3000:
                files_section += f"\n... ({len(content) - 3000} more chars)"

        prompt = f"""
You are planning a code fix for this GitHub issue.

## Issue
{issue.full_text}

## Relevant File Contents
{files_section}

## Task
Create a detailed fix plan. Think carefully about:
1. The root cause of the issue
2. The minimal change needed to fix it
3. How to match existing code style and conventions
4. What tests to add or modify
5. Edge cases to handle

Respond ONLY with a valid JSON object:
{{
  "summary": "One-sentence description of the fix",
  "approach": "Detailed explanation of the changes needed and why",
  "test_strategy": "How to test this fix — what test cases to add/modify",
  "risks": "Potential side effects or edge cases to watch for",
  "changes": [
    {{
      "filepath": "path/to/file.go",
      "description": "What to change in this file",
      "type": "modify"
    }}
  ]
}}
"""
        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
        )

        try:
            data = _extract_json(response)
            files = [
                FilePlan(
                    filepath=c.get("filepath", ""),
                    reason=c.get("description", ""),
                    action=c.get("type", "modify"),
                )
                for c in data.get("changes", [])
            ]
            return FixPlan(
                summary=data.get("summary", ""),
                files=files,
                approach=data.get("approach", ""),
                test_strategy=data.get("test_strategy", ""),
                risks=data.get("risks", ""),
            )
        except Exception as e:
            print(f"   ⚠️  Could not parse fix plan: {e}")
            return FixPlan(
                summary="Fix plan unavailable",
                files=[],
                approach=response[:500],
                test_strategy="",
                risks="",
            )
