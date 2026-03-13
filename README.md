<div align="center">

<pre>
 ██████╗ ██╗    ██╗██╗                ██████╗ ██╗      ██╗                 
██╔═══██╗██║    ██║██║               ██╔════╝ ██║      ██║      ,______,   
██║   ██║██║ █╗ ██║██║      ██████╗  ██║      ██║      ██║     ( O v O )   
██║   ██║██║███╗██║██║      ╚═════╝  ██║      ██║      ██║      /  V  \    
╚██████╔╝╚███╔███╔╝███████╗          ╚██████╗ ███████╗ ██║     /(     )\   
 ╚═════╝  ╚══╝╚══╝ ╚══════╝           ╚═════╝ ╚══════╝ ╚═╝     ^^   ^^     
</pre>

**Semantic code search powered by vector embeddings.**<br>
Search your codebase with natural language — at the function level.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![uv](https://img.shields.io/badge/uv-package%20manager-de5fe9)](https://docs.astral.sh/uv/)

[Features](#-features) · [Quick Start](#-quick-start) · [Usage](#-usage) · [Examples](#-real-world-examples) · [MCP Integration](#-mcp-integration) · [How It Works](#-how-it-works)

</div>

---

## 🎬 Demo

```
$ owl search "handle database connection"

╭───  #1 connect_db  score: 0.8923 ──────────────────────────────────╮
│   12 │ def connect_db(config: DBConfig) -> Connection:              │
│   13 │     """Establish database connection with retry logic."""     │
│   14 │     for attempt in range(config.max_retries):                │
│   15 │         try:                                                 │
│   16 │             conn = psycopg2.connect(config.dsn)              │
│   17 │             return conn                                      │
│   18 │         except OperationalError:                             │
│   19 │             time.sleep(2 ** attempt)                         │
│  db/connection.py:12-19                                             │
╰─────────────────────────────────────────────────────────────────────╯

╭───  #2 init_pool  score: 0.8471 ───────────────────────────────────╮
│   24 │ def init_pool(dsn: str, size: int = 10) -> Pool:             │
│   25 │     """Initialize a connection pool for the application."""   │
│   26 │     return ConnectionPool(dsn, min_size=2, max_size=size)    │
│  db/pool.py:24-26                                                   │
╰─────────────────────────────────────────────────────────────────────╯
```

> 💡 `grep "database"` → hundreds of noisy text matches<br>
> 🦉 `owl search "handle database connection"` → the exact functions you need

## 🌍 Real-World Examples

Searching the [Flask](https://github.com/pallets/flask) codebase with production code only.

**Step 1 — Auto-detect non-production files** with `owl config --auto-exclude`

![auto-exclude](docs/images/example-autoexclude.png)

owl scans the codebase and identifies tests, docs, and examples (59 files), leaving only `src/` (24 files · 388 functions) in the index.

**Step 2 — Search production code** — `owl search "user session management" -k 3`

![Session management search](docs/images/example-session.png)

Results point directly to `src/flask/sessions.py` — real implementation code, not test stubs.

**Step 3 — Search more** — `owl search "handle HTTP request routing" -k 3`

![HTTP request routing search](docs/images/example-routing.png)

**Check what's indexed** — `owl status`

![Index status](docs/images/example-status.png)

---

## ✨ Features

| | Feature | Description |
|---|---------|-------------|
| 🔍 | **Semantic Search** | Find code by meaning, not just keywords |
| 🎯 | **Function-Level Granularity** | Results are individual functions with file paths and line numbers |
| ⚡ | **Differential Caching** | Only re-embeds changed files; unchanged files reuse cached embeddings |
| 🔄 | **Auto-Indexing** | First search automatically builds the index |
| 🔀 | **Diff Analysis** | Find semantically related functions from git diff changes |
| 🔎 | **Similarity Detection** | Detect duplicate or similar implementations across the codebase |
| 🤖 | **MCP Server** | Integrates with Claude Code, GitHub Copilot, and other MCP tools |
| 📜 | **Search History** | Saves every query; supports annotations from LLMs or users |
| 📋 | **JSON Output** | Machine-readable output for scripting and tool integration |

## 🚀 Quick Start

**Requirements:** Python 3.12+ and [uv](https://docs.astral.sh/uv/)

```bash
# Install
uv tool install git+https://github.com/Shun0212/Owl-CLI.git

# Search (auto-indexes on first run)
owl search "authentication logic"

# Update to latest version
uv tool upgrade owl-cli
```

> The first run downloads the embedding model (~400MB) and auto-builds the index.

<details>
<summary>🔧 <code>owl</code> command not found?</summary>

Add `~/.local/bin` to your PATH:

```bash
# bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

</details>

<details>
<summary>⚡ Run without installing</summary>

```bash
uvx --from git+https://github.com/Shun0212/Owl-CLI.git owl search "authentication logic"
```

</details>

<details>
<summary>🛠️ Development setup</summary>

> **Note:** Development is done on macOS.

```bash
git clone https://github.com/Shun0212/Owl-CLI.git
cd Owl-CLI
uv sync
uv run owl search "query"
```

</details>

## 📖 Usage

### `owl search` — Find Code Semantically

```bash
owl search "authentication logic"           # basic search
owl search "error handling" -k 5            # limit results
owl search "database connection" -d ./proj  # specific directory
owl search "file parsing" --json            # JSON output
owl search "validation" --no-code           # function names only
owl search "config" -m my-org/custom-model  # custom model
```

### `owl index` — Build the Index

```bash
owl index                     # index current directory
owl index --force             # force full rebuild
owl index --dir ./my-project  # index specific directory
```

### `owl diff` — Semantic Diff Analysis

Find functions semantically related to your code changes. Unlike `git diff` which only shows _what_ changed, `owl diff` reveals _what else in the codebase is related_ to those changes.

```bash
owl diff                      # unstaged changes
owl diff --staged             # staged changes
owl diff HEAD~1               # last commit
owl diff main..feature        # branch comparison
owl diff HEAD~3 -k 3          # top 3 similar per change
owl diff HEAD~1 --threshold 0.7  # only high-similarity matches
owl diff HEAD~1 --json        # JSON output for CI/CD
```

> 💡 `git diff` → shows changed lines only<br>
> 🦉 `owl diff` → shows changed functions + semantically related code elsewhere

### `owl find-similar` — Duplicate & Similar Code Detection

Find duplicate or similar implementations across your codebase. Specify a function to see what else looks like it.

```bash
owl find-similar src/auth/login.py::validate_token  # specific function
owl find-similar src/utils.py                       # all functions in file
owl find-similar src/api.py::handle_request -k 5    # top 5 similar
owl find-similar lib/parser.rb::parse --threshold 0.6  # similarity cutoff
owl find-similar handlers/auth.go::Login --json     # JSON output
```

> 💡 "This code looks familiar…" → `owl find-similar` finds the other copies

### `owl status` — Check Index Status

```bash
$ owl status
```

```
         Owl-CLI Index Status
┌──────────────┬──────────────────────────┐
│ Directory    │ /home/user/my-project    │
│ Files        │ 42                       │
│ Functions    │ 187                      │
│ Model        │ Shuu12121/Owl-ph2-len20… │
│ Last indexed │ 2026-03-11 12:34:56      │
│ Cache size   │ 1.2 MB                   │
└──────────────┴──────────────────────────┘
```

### `owl history` — Search History

```bash
owl history                                  # recent history
owl history -n 50                            # more entries
owl history --json                           # JSON output
owl history --annotate 1 "useful result"     # annotate entry
owl history --clear                          # clear history
```

```
          Search History (showing 3 of 12)
┌───┬──────────────────┬──────────────────────┬─────────┬────────────┐
│ # │ Time             │ Query                │ Results │ Annotation │
├───┼──────────────────┼──────────────────────┼─────────┼────────────┤
│ 1 │ 2026-03-11 12:30 │ auth middleware       │       3 │            │
│ 2 │ 2026-03-11 12:35 │ database connection   │       5 │ useful!    │
│ 3 │ 2026-03-11 12:40 │ error handling        │       8 │            │
└───┴──────────────────┴──────────────────────┴─────────┴────────────┘
```

### `owl config` — Manage Configuration

```bash
owl config                   # show current configuration
owl config --clear-cache     # clear cache for current directory
owl config --clear-all-cache # clear all caches
```

## 🔌 MCP Integration

Owl-CLI works as an [MCP](https://modelcontextprotocol.io/) server, giving AI coding assistants semantic search capabilities.

Available tools: `search_code` · `index_code` · `index_status` · `diff_search` · `find_similar`

### Claude Code

```bash
# Recommended: register as MCP server
claude mcp add --transport stdio --scope user owl-cli -- owl mcp

# Or without global install
claude mcp add --transport stdio --scope user owl-cli -- \
  uvx --from git+https://github.com/Shun0212/Owl-CLI.git owl mcp
```

<details>
<summary>Enable auto-annotation</summary>

```bash
claude mcp add --transport stdio --scope user owl-cli -- \
  env OWL_AUTO_ANNOTATE=1 owl mcp
```

</details>

<details>
<summary>Alternative: Custom slash command</summary>

Copy `.claude/commands/owl-search.md` into your project's `.claude/commands/` directory, then use `/owl-search <query>` inside Claude Code.

</details>

### GitHub Copilot

Add `.vscode/mcp.json` to your project root:

```json
{
  "servers": {
    "owl-cli": {
      "command": "owl",
      "args": ["mcp"]
    }
  }
}
```

<details>
<summary>Without global install (uvx)</summary>

```json
{
  "servers": {
    "owl-cli": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Shun0212/Owl-CLI.git",
        "owl", "mcp"
      ]
    }
  }
}
```

</details>

<details>
<summary>Enable auto-annotation</summary>

```json
{
  "servers": {
    "owl-cli": {
      "command": "owl",
      "args": ["mcp"],
      "env": { "OWL_AUTO_ANNOTATE": "1" }
    }
  }
}
```

</details>

### Direct CLI

Any tool can invoke Owl-CLI directly:

```bash
owl search "error handling" --json
```

The `--json` flag outputs machine-readable results for any tool to consume.

## ⚙️ Configuration

Settings are resolved in priority order:

| Priority | Source | Example |
|:--------:|--------|---------|
| 1 | Defaults | `Shuu12121/Owl-ph2-len2048`, batch_size=8, top_k=10 |
| 2 | Config file | `~/.cache/owl-cli/<hash>/config.json` |
| 3 | Environment | `OWL_MODEL_NAME`, `OWL_BATCH_SIZE` |
| 4 (highest) | CLI flags | `--model`, `--top-k` |

> Caches live in `~/.cache/owl-cli/` — your project directory is never touched.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OWL_MODEL_NAME` | Sentence-transformer model name | `Shuu12121/Owl-ph2-len2048` |
| `OWL_BATCH_SIZE` | Encoding batch size | `8` |
| `OWL_TOP_K` | Default number of results | `10` |
| `OWL_AUTO_ANNOTATE` | LLM annotates search results via MCP (`1`/`true`/`yes`) | off |

### Config File

`.owl/config.json` in your project or `~/.cache/owl-cli/<hash>/config.json`:

```json
{
  "model_name": "Shuu12121/Owl-ph2-len2048",
  "batch_size": 16,
  "top_k": 10,
  "auto_annotate": true
}
```

## 🧠 How It Works

```
                    ┌──────────────────────────────┐
  source files ───▶ │  tree-sitter ──▶  functions  │
  (.py .js .ts     └──────────────┬───────────────┘
   .java .go .rb                  │
   .rs .php)        ┌──────────────▼───────────────┐
                    │    SentenceTransformers       │
                    │    encode to dense vectors    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       FAISS IndexFlatIP       │
                    │    (inner-product search)     │
                    └──────────────┬───────────────┘
                                   │
  "your query" ──▶ same model ──▶ compare ──▶ ranked results
```

1. **Extract** — tree-sitter parses source files, extracting every function/method with metadata
2. **Embed** — SentenceTransformers encodes each function into a dense vector (normalized for cosine similarity)
3. **Index** — FAISS `IndexFlatIP` stores vectors for fast inner-product search
4. **Search** — Your query is encoded with the same model and compared against all indexed functions
5. **Cache** — SHA-256 file hashes enable differential indexing; only changed files are re-processed

## 📁 Architecture

```
owl_cli/
├── cli.py                   # Click CLI entry point
├── config.py                # Configuration management
├── model.py                 # SentenceTransformer loading & encoding
├── indexer.py               # CodeSearchEngine (build + search + similarity)
├── diff.py                  # Git diff parsing & changed-function detection
├── cache.py                 # Cache management
├── history.py               # Search history & annotations
├── mcp_server.py            # FastMCP stdio server
└── extractors/
    ├── __init__.py              # Extension-based dispatch
    ├── python_extractor.py      # Python (tree-sitter)
    ├── javascript_extractor.py  # JavaScript / JSX (tree-sitter)
    ├── typescript_extractor.py  # TypeScript / TSX (tree-sitter)
    ├── java_extractor.py        # Java (tree-sitter)
    ├── go_extractor.py          # Go (tree-sitter)
    ├── ruby_extractor.py        # Ruby (tree-sitter)
    ├── rust_extractor.py        # Rust (tree-sitter)
    └── php_extractor.py         # PHP (tree-sitter)
```

## 🌐 Supported Languages

| Language | Extensions | Extraction |
|----------|-----------|------------|
| Python | `.py` | functions, methods, classes |
| JavaScript | `.js`, `.jsx` | functions, methods, arrow functions |
| TypeScript | `.ts`, `.tsx` | functions, methods, arrow functions |
| Java | `.java` | methods, constructors |
| Go | `.go` | functions, methods (with receiver type) |
| Ruby | `.rb` | methods, singleton methods |
| Rust | `.rs` | functions (with `impl` block detection) |
| PHP | `.php` | functions, methods |

All languages are enabled by default. Each uses [tree-sitter](https://tree-sitter.github.io/) for accurate AST-based function extraction.

## 🤝 Contributing

Contributions are welcome!

```bash
git clone https://github.com/Shun0212/Owl-CLI.git
cd Owl-CLI
uv sync
uv run pytest          # run tests
uv run owl search "q"  # test locally
```

## 📄 License

[MIT](LICENSE) © [Shun0212](https://github.com/Shun0212)
