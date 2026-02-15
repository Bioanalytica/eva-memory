# Engram Vault Architecture (EVA) Memory

Three-layer persistent memory for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Memories survive across sessions using markdown files, a Neo4j graph database, and optional ChromaDB semantic search.

## Features

- **Three storage layers** — markdown (always available), Neo4j graph (relationships + full-text search), ChromaDB (semantic similarity via Ollama embeddings)
- **Graceful degradation** — works with just Neo4j, scales up when ChromaDB/Ollama are available
- **10 MCP tools** — remember, search, update, forget, recall, summarize, list, instructions, entities, maintain
- **Lifecycle hooks** — automatic context injection on session start, backup before compaction, clean shutdown
- **WAL crash safety** — write-ahead log ensures no memory loss on unexpected shutdown
- **Duplicate detection** — semantic similarity (>0.92 = skip, >0.5 = auto-supersede) with fulltext fallback
- **Confidence scoring** — 0.0–1.0 scale to track how certain a memory is
- **Memory decay** — `decayDays` auto-expires transient memories
- **Standing instructions** — `instruction`-type memories injected into every session
- **Entity extraction** — automatic topic/entity detection and Neo4j graph linking
- **Client isolation** — `EVA_CLIENT_ID` namespaces state files when multiple clients share the same data

## Quick Start

### Prerequisites

- [Bun](https://bun.sh) — runs the MCP server and hooks
- [uv](https://docs.astral.sh/uv/) — runs the Python core engine
- [Docker](https://docs.docker.com/get-docker/) — for Neo4j and ChromaDB
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — the AI coding assistant

### 1. Clone and install

```bash
git clone https://github.com/Bioanalytica/eva-memory.git
cd eva-memory
./install.sh
```

### 2. Start services

```bash
cp .env.example .env
# Edit .env — set EVA_NEO4J_PASS at minimum
docker compose up -d
```

### 3. Initialize the database

```bash
EVA_NEO4J_PASS=yourpassword uv run scripts/init_schema.py
```

### 4. Register with Claude Code

```bash
claude mcp add eva-memory \
  --scope user \
  -e EVA_MEMORY_DIR="$(pwd)" \
  -e EVA_NEO4J_URI="bolt://localhost:7687" \
  -e EVA_NEO4J_PASS="yourpassword" \
  -e EVA_STORE_PATH="$HOME/.eva-memory" \
  -- bun run "$(pwd)/mcp-server/src/index.ts"
```

### 5. Add hooks to `~/.claude/settings.json`

Merge the contents of `config/settings-hooks.json` into your existing settings file. Replace `$EVA_MEMORY_DIR` with your absolute path to this repo.

### 6. Verify

Start a new Claude Code session. You should see the SessionStart hook fire in stderr. Then test:

```
> Remember that I prefer dark mode in all my applications
> What are my preferences?
```

## Architecture

```
  Claude Code
       │
       ├── MCP Server (bun + TypeScript)
       │        │
       │        └── bridge.ts ──spawns──▶ uv run memory.py <command> <json>
       │
       └── Hooks (SessionStart, PreCompact, SessionEnd)
                │
                └── bridge.ts ──spawns──▶ uv run memory.py <command> <json>

  memory.py writes to three layers:

       ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐
       │  Markdown    │   │   Neo4j     │   │    ChromaDB     │
       │  (daily +    │   │  (graph +   │   │   (semantic     │
       │   project    │   │   fulltext  │   │    via Ollama)  │
       │   logs)      │   │   search)   │   │                 │
       └─────────────┘   └─────────────┘   └─────────────────┘
         always            required           optional
```

## Tools

| Tool | MCP Name | Description |
|------|----------|-------------|
| Remember | `mcp__eva-memory__remember` | Store a memory with type, importance, confidence, decay, tags |
| Search | `mcp__eva-memory__search` | Search across all layers (fulltext + semantic) |
| Update | `mcp__eva-memory__update` | Modify existing memory content/metadata, re-embeds automatically |
| Forget | `mcp__eva-memory__forget` | Soft-delete by ID or search query, with audit reason |
| Recall | `mcp__eva-memory__recall` | Retrieve specific memories by ID or filter |
| Summarize | `mcp__eva-memory__summarize` | Topic summary grouped by memory type |
| List | `mcp__eva-memory__list` | Paginated browsing with sorting |
| Instructions | `mcp__eva-memory__instructions` | List active standing instructions |
| Entities | `mcp__eva-memory__entities` | List entities from the knowledge graph |
| Maintain | `mcp__eva-memory__maintain` | Prune expired/low-importance memories |

## Hooks Lifecycle

```
  Session Start/Resume          Context Compaction           Session End
  ┌──────────────────┐          ┌──────────────────┐        ┌──────────────┐
  │ eva-session-start│          │ eva-pre-compact  │        │eva-session-end│
  │                  │          │                  │        │              │
  │ 1. sync-start   │          │ 1. WAL flush     │        │ 1. sync-end  │
  │ 2. auto-recall  │──inject──│ 2. backup        │        │              │
  │    inject context│  context │                  │        └──────────────┘
  └──────────────────┘         └──────────────────┘
```

- **SessionStart** fires on startup, resume, and after compaction. Injects standing instructions and high-importance memories as a `<system-reminder>`.
- **PreCompact** fires before context compression. Creates a backup snapshot and flushes the WAL.
- **SessionEnd** fires on session close. Writes session summary and cleans up.

Subagents are detected (`CLAUDE_CODE_AGENT` / `SUBAGENT=true`) and skipped — only the main session manages memory.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EVA_NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection URI |
| `EVA_NEO4J_USER` | `neo4j` | Neo4j username |
| `EVA_NEO4J_PASS` | — | Neo4j password (**required**) |
| `EVA_STORE_PATH` | `~/.eva-memory` | Data directory for markdown, state, queue |
| `EVA_MEMORY_DIR` | (auto-detected) | Root directory of this repo |
| `EVA_CHROMA_URL` | — | ChromaDB URL (optional) |
| `EVA_OLLAMA_URL` | — | Ollama API URL (optional) |
| `EVA_CHROMA_COLLECTION` | — | ChromaDB collection UUID |
| `EVA_OLLAMA_MODEL` | `nomic-embed-text` | Embedding model |
| `EVA_RECALL_MAX_TOKENS` | `400` | Token budget for auto-recall injection |
| `EVA_RECALL_MIN_IMPORTANCE` | `3` | Minimum importance for auto-recall |
| `EVA_RECALL_MAX_RESULTS` | `5` | Max memories per auto-recall |
| `EVA_INJECT_INSTRUCTIONS` | `true` | Inject standing instructions on session start |
| `EVA_COMMAND_TIMEOUT_MS` | `10000` | Timeout for memory.py subprocess calls (ms) |
| `EVA_CLIENT_ID` | — | Client namespace for state isolation |

See `.env.example` for a fully commented template.

## Memory Types

| Type | Description | Recommended Decay |
|------|-------------|-------------------|
| `instruction` | Standing orders ("always X", "never Y"). Auto-injected every session. | Permanent |
| `decision` | Choices made with rationale | Permanent |
| `preference` | Likes, dislikes, style choices | Permanent |
| `learning` | Insights, discoveries | Permanent |
| `task` | TODOs, planned work | 30–90 days |
| `progress` | Milestones, completions | 30–90 days |
| `question` | Open questions, research topics | 14–30 days |
| `note` | General observations | Varies |
| `info` | General information (default) | Varies |

## Data Directory

```
~/.eva-memory/
├── state.json                  # WAL, session state, stats
├── config.json                 # Runtime configuration
├── MEMORY.md                   # Human-readable memory summary
├── SESSION-STATE.md            # Current session working memory
├── daily/
│   └── 2026-02-14.md           # Daily memory log
├── projects/
│   └── my-project.md           # Project-specific memories
├── queue/
│   └── pending-embeddings.jsonl # Offline ChromaDB queue
└── backups/
    └── pre-compaction/         # Snapshots before context loss
```

## Advanced

### Enabling Semantic Search (ChromaDB + Ollama)

1. Start Ollama and pull the embedding model:
   ```bash
   # Option A: run on host (recommended for GPU)
   ollama pull nomic-embed-text

   # Option B: run in Docker
   docker compose --profile gpu up -d
   docker exec eva-ollama ollama pull nomic-embed-text
   ```

2. Create a ChromaDB collection:
   ```bash
   curl -X POST http://localhost:8000/api/v1/collections \
     -H 'Content-Type: application/json' \
     -d '{"name": "eva-memory"}'
   ```
   Copy the returned `id` (UUID) into `EVA_CHROMA_COLLECTION`.

3. Set the environment variables:
   ```bash
   EVA_CHROMA_URL=http://localhost:8000
   EVA_OLLAMA_URL=http://localhost:11434
   EVA_CHROMA_COLLECTION=<uuid-from-step-2>
   ```

### Client Isolation

When multiple Claude Code instances share the same data directory, set a unique `EVA_CLIENT_ID` per client:

```bash
EVA_CLIENT_ID=claude-code-work   # in one instance
EVA_CLIENT_ID=claude-code-home   # in another
```

This namespaces `state.json` and `SESSION-STATE.md`. The memory database (Neo4j, ChromaDB, markdown logs) is shared.

### CLI Usage

The Python engine can be called directly for debugging:

```bash
# Store a memory
uv run scripts/memory.py remember '{"content":"prefer dark mode","type":"preference","importance":7}'

# Search
uv run scripts/memory.py search '{"query":"dark mode"}'

# List all memories
uv run scripts/memory.py list '{"sortBy":"importance","sortOrder":"DESC"}'
```

All commands accept JSON and return JSON to stdout.

## Troubleshooting

**MCP server not connecting**
- Verify `claude mcp list` shows `eva-memory`
- Check that `EVA_MEMORY_DIR` points to this repo's absolute path
- Ensure `bun` and `uv` are in your PATH

**Hooks not firing**
- Verify hooks are in `~/.claude/settings.json` under the correct event names
- Check that `$EVA_MEMORY_DIR` is expanded (not a literal `$` in the JSON)
- Look at stderr output in the Claude Code terminal for `[eva-memory]` messages

**Neo4j connection refused**
- Ensure `docker compose up -d` is running
- Check `EVA_NEO4J_URI` matches your setup (default: `bolt://localhost:7687`)
- Verify the password matches: `EVA_NEO4J_PASS`

**"memory.py exited 1"**
- Run the command manually to see the error: `uv run scripts/memory.py search '{"query":"test"}'`
- Check that Python dependencies resolve: `uv run --script scripts/memory.py --help` (not a real flag, but tests imports)

**ChromaDB offline (graceful)**
- This is expected if you haven't set up ChromaDB. The system queues embeddings to `queue/pending-embeddings.jsonl` and drains them when ChromaDB comes back.

## License

MIT — see [LICENSE](LICENSE).
