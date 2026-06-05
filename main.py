#!/usr/bin/env python3
"""
AI Go Contributor - Main Entry Point
Usage: python main.py <github-issue-url> [--output-dir ./output]
"""

import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from agent.agent import GoContributorAgent

# Load environment variables from .env file
load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agentic AI Contributor for Open-Source Go Projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py https://github.com/spf13/cobra/issues/1234
  python main.py https://github.com/gin-gonic/gin/issues/567 --output-dir ./my_output
  python main.py https://github.com/spf13/cobra/issues/1234 --dry-run
        """
    )
    parser.add_argument(
        "issue_url",
        help="GitHub issue URL (e.g. https://github.com/spf13/cobra/issues/123)"
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to save output files (default: ./output)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — do not modify files or run tests"
    )
    parser.add_argument(
        "--llm",
        default="gemini",
        choices=["gemini", "groq", "ollama"],
        help="LLM backend to use (default: gemini)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model name (e.g. gemini-2.5-pro, llama-3.3-70b-versatile)"
    )
    parser.add_argument(
        "--workspace",
        default="./workspace",
        help="Directory to clone repositories into (default: ./workspace)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Validate environment
    from agent.config import Config
    config = Config(
        llm_backend=args.llm,
        model_override=args.model,
        workspace_dir=args.workspace,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    missing = config.validate()
    if missing:
        print(f"\n❌ Missing required environment variables:\n")
        for var, hint in missing:
            print(f"   {var}: {hint}")
        print("\nSee README.md for setup instructions.\n")
        sys.exit(1)

    print("\n" + "="*60)
    print("  🤖 AI Go Contributor")
    print("="*60)
    print(f"  Issue : {args.issue_url}")
    print(f"  LLM   : {config.llm_backend} / {config.model}")
    print(f"  Mode  : {'DRY RUN' if args.dry_run else 'FULL'}")
    print("="*60 + "\n")

    agent = GoContributorAgent(config)
    result = agent.run(args.issue_url)

    if result.success:
        print("\n" + "="*60)
        print("  ✅ Completed Successfully")
        print("="*60)
        print(f"  Diff      : {result.diff_path}")
        print(f"  PR Summary: {result.pr_summary_path}")
        print(f"  Full log  : {result.log_path}")
        print("="*60 + "\n")
        print("📋 PR Summary Preview:")
        print("-"*60)
        print(result.pr_summary[:800] + ("..." if len(result.pr_summary) > 800 else ""))
        print("-"*60 + "\n")
    else:
        print("\n❌ Agent failed:", result.error)
        sys.exit(1)


if __name__ == "__main__":
    main()
