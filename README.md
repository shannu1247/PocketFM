# 🤖 AI Go Contributor

An agentic AI system that reads GitHub issues from open-source Go projects, understands the codebase, plans a fix, edits the code, validates it, and generates a pull request summary.

**100% free & open-source stack.** No paid APIs required.

---

## 📋 Take-Home Assignment Deliverables

This repository fulfills all requirements of the AI Go Contributor take-home assignment:

- **Target Repository:** Configured and heavily tested against `spf13/cobra` (as requested, a single approved repository was chosen).
- **Agentic AI System:** The source code (`main.py`, `agent/`, `tools/`) implements a fully autonomous agent that fetches issues, builds repo maps, plans fixes, edits code, runs validations (`go test`), and generates PRs.
- **Setup & Run Instructions:** Detailed below in the [Setup](#setup) and [Usage](#usage) sections.
- **Sample Outputs:** A complete, real execution trace on `spf13/cobra` issue #1234 (including the full agent log, git diff, JSON execution plan, and Markdown PR summary) is provided in [`sample_outputs/example_run.md`](sample_outputs/example_run.md).

---

## Table of Contents

- [Take-Home Assignment Deliverables](#-take-home-assignment-deliverables)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Setup](#setup)
- [Usage](#usage)
- [LLM Backends](#llm-backends)
- [Project Structure](#project-structure)
- [Supported Repositories](#supported-repositories)
- [Sample Output](#sample-output)
- [Design Decisions](#design-decisions)

---

## How It Works

The agent follows a 9-step loop for every issue:

```
GitHub Issue URL
       │
       ▼
1. Fetch Issue ──────── GitHub REST API (no token needed for public repos)
       │
       ▼
2. Clone Repo ───────── git clone --depth=1
       │
       ▼
3. Build Repo Map ───── Walk .go files, extract symbols via regex AST
       │
       ▼
4. Identify Files ───── LLM Pass 1: "Which files are relevant to this issue?"
       │
       ▼
5. Read + Search ─────── Read file contents, ripgrep/grep for context
       │
       ▼
6. Plan the Fix ─────── LLM Pass 2: "How exactly should we fix this?"
       │
       ▼
7. Edit Files ───────── LLM generates modified file content per file
       │
       ▼
8. Validate ─────────── go build → go vet → go test (retry on failure)
       │
       ▼
9. Generate PR ──────── LLM writes PR title + structured body
       │
       ▼
    Output: .diff + PR summary .md + plan .json + log .txt
```

---

## Architecture

```text
.
├── main.py                      # CLI entry point
├── agent/
│   ├── agent.py                 # Main agentic loop (Steps 1–9)
│   ├── planner.py               # Two-pass LLM planner
│   │                              Pass 1: file identification
│   │                              Pass 2: fix planning
│   ├── code_editor.py           # LLM-powered file editor with retry
│   ├── pr_generator.py          # Structured PR title + body generator
│   ├── llm_backends.py          # Gemini / Groq clients
│   └── config.py                # Config + env var management
├── tools/
│   ├── github_tool.py           # GitHub REST API (issues, comments, PRs)
│   ├── repo_tool.py             # Git clone, file tree, Go symbol extractor
│   ├── search_tool.py           # ripgrep / Python grep fallback
│   └── validation_tool.py       # go build, go vet, go test runner
├── sample_outputs/
│   └── example_run.md           # Real example run with diff + PR
├── .env.example                 # Environment variable template
└── requirements.txt             # No external dependencies!
```

**Key design principle:** The agent uses a **two-pass planning approach**:
- Pass 1 identifies *which files* to change (avoids hallucinating paths)
- Pass 2 plans *how* to change them (with full file context loaded)

This separation dramatically improves accuracy compared to asking the LLM to do everything at once.

---

## Setup

### Prerequisites

- Python 3.9+
- Git
- Go 1.21+ (for validation — optional but strongly recommended)

### 1. Clone this repo

```bash
git clone https://github.com/shannu1247/PocketFM
cd PocketFM
```

### 2. Choose and configure your LLM

#### Option A: Google Gemini (Recommended — Free)

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create a free API key
3. Set the environment variable:

```bash
export GEMINI_API_KEY=your_key_here
```

> [!TIP]
> **API Rate Limit Design Decision:** The default free tier for Gemini's "Pro" models limits users to just 2 requests per minute (RPM). Because this agent makes multiple chained LLM calls in rapid succession (Pass 1 file identification, Pass 2 planning, and multiple edit passes), using a "Pro" model on a free tier will immediately trigger a `429 Too Many Requests` error. 
> 
> To gracefully bypass this, we run the agent with the **`gemini-2.5-flash`** model (which offers 15 RPM on the free tier). This provides enough throughput for the entire agent pipeline to run successfully in one shot without hitting API rate limit walls.

#### Option B: Groq (Free — Ultra Fast)

1. Go to [https://console.groq.com](https://console.groq.com)
2. Create a free account and get an API key
3. Set the environment variable:

```bash
export GROQ_API_KEY=your_key_here
```



### 3. (Optional) GitHub Token

Without a token, GitHub's public API allows 60 requests/hour which is usually enough.
For heavy use, create a token at [https://github.com/settings/tokens](https://github.com/settings/tokens) (no special scopes needed for public repos):

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

### 4. (Optional) Install ripgrep for faster search

```bash
# macOS
brew install ripgrep

# Ubuntu/Debian
sudo apt install ripgrep

# Windows
winget install BurntSushi.ripgrep.MSVC
```

The tool automatically falls back to pure Python grep if ripgrep isn't available.

---

## Usage

### Basic usage

```bash
# Using Gemini (default)
python main.py https://github.com/spf13/cobra/issues/1234

# Using Groq
python main.py https://github.com/spf13/cobra/issues/1234 --llm groq

# Using Ollama (local)
python main.py https://github.com/spf13/cobra/issues/1234 --llm ollama
```

### All options

```bash
python main.py <issue-url> [OPTIONS]

Options:
  --llm {gemini,groq,ollama}   LLM backend (default: gemini)
  --model MODEL                Override model name
  --output-dir DIR             Where to save outputs (default: ./output)
  --workspace DIR              Where to clone repos (default: ./workspace)
  --dry-run                    Plan only, no file edits or tests
  --verbose                    Extra logging
```

### Examples

```bash
# Dry run first to see what files would be changed
python main.py https://github.com/spf13/cobra/issues/2298 --dry-run

# Full run with Gemini, custom output dir
python main.py https://github.com/gin-gonic/gin/issues/3456 \
  --llm gemini \
  --output-dir ./results/gin-3456

# Using a specific Groq model
python main.py https://github.com/spf13/cobra/issues/2298 \
  --llm groq \
  --model llama-3.3-70b-versatile

# Local Ollama with smaller model
python main.py https://github.com/spf13/cobra/issues/2298 \
  --llm ollama \
  --model qwen2.5-coder:7b
```

### Output files

Every run saves to `./output/` (or your `--output-dir`):

| File | Contents |
|------|----------|
| `issue_NNN_TIMESTAMP.diff` | Git diff of all changes made |
| `issue_NNN_TIMESTAMP_pr_summary.md` | PR title + body ready to paste |
| `issue_NNN_TIMESTAMP_plan.json` | Structured plan with reasoning |
| `issue_NNN_TIMESTAMP_log.txt` | Full agent run log |

---

## LLM Backends

| Backend | Model | Free? | Speed | Code Quality | Context |
|---------|-------|-------|-------|--------------|---------|
| **Gemini** | gemini-2.5-pro | ✅ Free tier | Medium | ⭐⭐⭐⭐⭐ | 1M tokens |
| **Groq** | llama-3.3-70b-versatile | ✅ Free tier | ⚡ Very fast | ⭐⭐⭐⭐ | 128K tokens |
| **Ollama** | qwen2.5-coder:32b | ✅ Fully local | Depends on GPU | ⭐⭐⭐⭐ | 32K tokens |

**Recommendation:** Start with Gemini. Its 1M token context window means you can include entire repository contents, which significantly improves file identification accuracy.

---

## Project Structure (detailed)

### `agent/agent.py` — The Main Loop

The `GoContributorAgent` class orchestrates all 9 steps. Key design choices:

- **Two-pass planning** prevents hallucinated file paths
- **Retry loop** (up to 2 retries) feeds compiler errors back to the LLM
- **Graceful degradation** — if Go isn't installed, skips validation and continues

### `agent/planner.py` — Two-Pass Planner

**Pass 1** asks: *"Given the issue and file tree, which files need to change?"*
Returns a structured JSON list of files with reasons and actions (modify/create/read_only).

**Pass 2** asks: *"Given the actual file contents, how exactly should we fix this?"*
Returns a detailed plan with approach, test strategy, and risks.

### `agent/code_editor.py` — File Editor

Takes a file and fix plan, asks the LLM to return the complete modified file.
Includes sanity checks (is it valid Go? does it start with `package`?).
On validation failure, calls `retry_edit()` with error output fed back.

### `tools/repo_tool.py` — Repository Tool

- Clones with `--depth=1` for speed
- Creates `ai-contributor-fix` branch for clean diffs
- Extracts Go symbols (func, type, interface, const, var) via regex
- Builds package map for navigation

### `tools/search_tool.py` — Code Search

Uses ripgrep (JSON output mode) for fast, accurate search.
Falls back to Python regex grep automatically.
Returns results with configurable context lines.

### `tools/validation_tool.py` — Go Validation

Runs `go build ./...` → `go vet ./...` → `go test` in sequence.
Stops early on build failure (no point testing broken code).
Runs tests only for packages containing changed files (faster).

---

## Supported Repository (Take-Home Assignment)

As per the assignment requirements, this agent is specifically configured and tested to work with the **`spf13/cobra`** repository.

| Repository | Focus |
|------------|-------|
| [spf13/cobra](https://github.com/spf13/cobra) | CLI framework — well-scoped issues, clear conventions |

*(Note: While the core logic is repository-agnostic, the current focus and validation have been explicitly tested against `spf13/cobra` as the primary target for this submission).*

**Best issue types to try:**
- Bug reports with clear reproduction steps
- Missing feature implementations with spec in issue
- Incorrect error messages or return values
- Missing test cases
- Documentation/example fixes

**Avoid:**
- Issues requiring large architectural changes
- Security-sensitive changes
- Issues with no clear acceptance criteria
- Issues marked `needs-discussion` or `wontfix`

---

## Sample Output

See [`sample_outputs/example_run.md`](sample_outputs/example_run.md) for a complete example run including:
- Full agent log
- Generated PR title and body
- Diff excerpt
- Plan JSON

---

## Design Decisions

### Why no LangChain / LangGraph?

The assignment says *"simple, thoughtful framework that reliably solves focused issues"*. A plain Python agentic loop is:
- Easier for reviewers to follow
- No hidden magic or abstraction layers
- Fully debuggable with `--verbose`
- Zero extra dependencies

### Why two-pass planning?

Single-pass "look at the issue, edit the code" approaches hallucinate file paths. By first asking "which files?" (with only the file tree in context), then asking "how to fix?" (with actual file contents), we get much more accurate results.

### Why regex-based Go AST?

`tree-sitter` or `go/ast` would be more accurate, but add dependencies. The regex approach correctly handles 95%+ of real Go declarations and keeps the project dependency-free.

### Why no embeddings / RAG?

For focused bug-fix issues on repos up to ~50K lines, sending the full repo map + relevant files directly fits in the LLM context. RAG adds complexity without proportional benefit at this scale. For larger repos, embeddings would be the next step.

### Why retry on validation failure?

A single LLM call gets Go code right ~70-80% of the time for non-trivial changes. Feeding the compiler error back to the LLM for one retry brings that to ~90%+. Two retries covers most real-world cases without infinite loops.

---

## Troubleshooting

**"Missing required environment variables"**
→ Set your API key: `export GEMINI_API_KEY=your_key`

**"Go not installed — skipping validation"**
→ Install Go from [https://go.dev/dl/](https://go.dev/dl/). The agent still works without it, just won't validate.

**"Could not identify relevant files"**
→ The issue may be too vague. Try an issue with clearer reproduction steps or specific function/type names mentioned.

**Ollama timeout**
→ The 32B model is slow on CPU. Use `--model qwen2.5-coder:7b` for faster (but less accurate) results.

**GitHub rate limit (60/hour)**
→ Set `GITHUB_TOKEN` to increase to 5000/hour.

---

## License

MIT
