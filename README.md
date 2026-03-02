# Owl-CLI

Semantic code search using vector embeddings. Search your codebase with natural language queries at the function level.

## Features

- **Semantic search** -- Find code by meaning, not just keywords
- **Function-level granularity** -- Results are individual functions/methods with file paths and line numbers
- **Differential caching** -- Only re-embeds changed files; unchanged files reuse cached embeddings
- **Auto-indexing** -- First search automatically builds the index
- **MCP server** -- Integrates with Claude Code, OpenCode, and other MCP-compatible tools
- **JSON output** -- Machine-readable output for scripting and tool integration

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Installation

```bash
# Install globally (recommended)
uv tool install git+https://github.com/Shun0212/Owl-CLI.git

# Now use `owl` anywhere
owl search "authentication logic"
```

Or run without installing:

```bash
uvx --from git+https://github.com/Shun0212/Owl-CLI.git owl search "authentication logic"
```

The first run will download the embedding model (~400MB) from Hugging Face.

### For development

```bash
git clone https://github.com/Shun0212/Owl-CLI.git
cd Owl-CLI
uv sync
uv run owl search "query"
```

## Usage

### Search

```bash
# Basic search (auto-indexes on first run)
owl search "authentication logic"

# Limit results
owl search "error handling" -k 5

# Search a specific directory
owl search "database connection" --dir ./my-project

# JSON output (for scripting)
owl search "file parsing" --json

# Show only function names without code bodies
owl search "validation" --no-code

# Use a different model
owl search "config loading" --model Shuu12121/Owl-ph2-len2048
```

### Index

```bash
# Build index for current directory
owl index

# Force full rebuild (ignore cache)
owl index --force

# Index a specific directory
owl index --dir ./my-project
```

### Status

```bash
owl status
```

```
┌──────────────┬─────────────────────────────────────────┐
│ Directory    │ /path/to/project                        │
│ Files        │ 9                                       │
│ Functions    │ 36                                      │
│ Model        │ Shuu12121/Owl-ph2-len2048 │
│ Last indexed │ 2026-03-03 02:37:57                     │
│ Cache size   │ 247.8 KB                                │
└──────────────┴─────────────────────────────────────────┘
```

### Config

```bash
# Show current configuration
owl config

# Clear cache
owl config --clear-cache
```

## Configuration

Settings are resolved in this order (later overrides earlier):

1. **Defaults** -- `Shuu12121/Owl-ph2-len2048`, batch_size=8, top_k=10
2. **`.owl/config.json`** -- Project-local config file
3. **Environment variables** -- `OWL_MODEL_NAME`, `OWL_BATCH_SIZE`, `OWL_TOP_K`
4. **CLI flags** -- `--model`, `--top-k`

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OWL_MODEL_NAME` | Sentence-transformer model name | `Shuu12121/Owl-ph2-len2048` |
| `OWL_BATCH_SIZE` | Encoding batch size | `8` |
| `OWL_TOP_K` | Default number of results | `10` |

### `.owl/config.json` example

```json
{
  "model_name": "Shuu12121/Owl-ph2-len2048",
  "batch_size": 16,
  "top_k": 20
}
```

## Claude Code Integration

### Option 1: MCP Server (Recommended)

Register the MCP server so Claude Code can call `search_code`, `index_code`, and `index_status` as tools:

```bash
# If installed via uv tool install
claude mcp add --transport stdio --scope user owl-cli -- owl mcp

# Or run directly without installing
claude mcp add --transport stdio --scope user owl-cli -- \
  uvx --from git+https://github.com/Shun0212/Owl-CLI.git owl mcp
```

Once registered, Claude Code can semantically search your codebase during conversations.

### Option 2: Custom Slash Command

Copy `.claude/commands/owl-search.md` into your project's `.claude/commands/` directory. Then use `/owl-search <query>` inside Claude Code.

### Option 3: Direct CLI

Claude Code and OpenCode can invoke the CLI directly via shell:

```bash
owl search "error handling" --json
```

The `--json` flag outputs machine-readable results for any tool to consume.

## How It Works

1. **Extract** -- tree-sitter parses Python source files and extracts every function/method with metadata (name, class, line range)
2. **Embed** -- sentence-transformers encodes each function's source code into a dense vector (normalized for cosine similarity)
3. **Index** -- FAISS `IndexFlatIP` stores vectors for fast inner-product search
4. **Search** -- Your query is encoded with the same model and compared against all indexed functions
5. **Cache** -- SHA-256 file hashes enable differential indexing; only changed files are re-processed

## Supported Languages

Currently Python (`.py`). The extractor architecture supports adding more languages by creating new files in `owl_cli/extractors/`.

## Architecture

```
owl_cli/
├── cli.py                   # Click CLI entry point
├── config.py                # Configuration management
├── model.py                 # SentenceTransformer loading and encoding
├── indexer.py               # CodeSearchEngine (build + search)
├── cache.py                 # .owl/ cache management
├── mcp_server.py            # FastMCP stdio server
└── extractors/
    ├── __init__.py           # Extension-based dispatch
    └── python_extractor.py   # tree-sitter Python function extraction
```

## License

See [LICENSE](LICENSE).
