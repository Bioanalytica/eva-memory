# Changelog

## v3.1.0 — 2026-02-14

- Standalone public release (removed OpenClaw/PAI platform dependencies)
- Added docker-compose.yml with Neo4j, ChromaDB, and optional Ollama
- Added install.sh for guided setup
- Fixed STORE_PATH default to use ~/.eva-memory instead of hardcoded path
- Comprehensive README with quick-start guide

---

## v3.0.0 — 2026-02-10

### Overview

Claude Code integration via MCP server and lifecycle hooks. EVA memory now runs natively in Claude Code with the same `memory.py` core, bridged through a TypeScript MCP server using `@modelcontextprotocol/sdk`. Three hooks manage session lifecycle (start, pre-compact, end), and client isolation namespaces state files per client.

### New Features

#### MCP Server
- 10 tools exposed via `@modelcontextprotocol/sdk` over stdio transport
- Bun/TypeScript bridge pattern: MCP server spawns `uv run memory.py <command>` per call
- Configurable via environment variables (no config file needed)

#### Lifecycle Hooks
- **SessionStart** (`eva-session-start.ts`): Fires on startup/resume/compact. Runs `sync-start`, then injects auto-recall context (`<system-reminder>` with standing instructions + important memories)
- **PreCompact** (`eva-pre-compact.ts`): Fires before context compaction. Creates backup snapshot and flushes WAL
- **SessionEnd** (`eva-session-end.ts`): Fires on session close. Runs `sync-end` for clean shutdown
- Subagent detection: hooks skip when `CLAUDE_CODE_AGENT` or `SUBAGENT=true` is set

#### Client Isolation
- `EVA_CLIENT_ID` environment variable namespaces state files per client
- Prevents session/state conflicts when multiple clients share the same `EVA_MEMORY_DIR`

#### Core Changes
- `memory.py` accepts external `sessionId` parameter for hook-driven session management
- MCP tool names follow `mcp__eva-memory__<tool>` convention in Claude Code

### New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EVA_MEMORY_DIR` | (parent of mcp-server/) | Root directory containing scripts/, hooks/, data/ |
| `EVA_RECALL_MAX_TOKENS` | `400` | Token budget for auto-recall injection |
| `EVA_RECALL_MIN_IMPORTANCE` | `3` | Minimum importance for auto-recall |
| `EVA_RECALL_MAX_RESULTS` | `5` | Max memories injected per session start |
| `EVA_INJECT_INSTRUCTIONS` | `true` | Whether to inject standing instructions |
| `EVA_COMMAND_TIMEOUT_MS` | `10000` | Timeout for memory.py subprocess calls |
| `EVA_CLIENT_ID` | — | Client namespace for state file isolation |

### MCP Tools

| MCP Tool Name | CLI Command | Description |
|---------------|-------------|-------------|
| `remember` | `remember` | Store a memory |
| `search` | `search` | Search across all layers |
| `update` | `update` | Modify existing memory |
| `forget` | `forget` | Smart soft-delete |
| `summarize` | `summarize` | Topic summary |
| `list` | `list` | Paginated browse |
| `recall` | `recall` | Retrieve specific memories |
| `instructions` | `instructions` | List standing instructions |
| `entities` | `entities` | List entities and connections |
| `maintain` | `maintain` | Run maintenance/pruning |

### Files Created

| File | Lines | Description |
|------|-------|-------------|
| `mcp-server/package.json` | 14 | MCP server package config |
| `mcp-server/tsconfig.json` | 14 | TypeScript config |
| `mcp-server/src/index.ts` | 32 | MCP server entry point |
| `mcp-server/src/bridge.ts` | 53 | Python subprocess bridge |
| `mcp-server/src/config.ts` | 27 | Environment config loader |
| `mcp-server/src/tools/remember.ts` | 86 | Remember tool |
| `mcp-server/src/tools/search.ts` | 56 | Search tool |
| `mcp-server/src/tools/update.ts` | 38 | Update tool |
| `mcp-server/src/tools/forget.ts` | 31 | Forget tool |
| `mcp-server/src/tools/summarize.ts` | 43 | Summarize tool |
| `mcp-server/src/tools/list.ts` | 44 | List tool |
| `mcp-server/src/tools/recall.ts` | 44 | Recall tool |
| `mcp-server/src/tools/instructions.ts` | 48 | Instructions tool |
| `mcp-server/src/tools/entities.ts` | 49 | Entities tool |
| `mcp-server/src/tools/maintain.ts` | 45 | Maintain tool |
| `hooks/eva-session-start.ts` | 153 | SessionStart hook |
| `hooks/eva-session-end.ts` | 28 | SessionEnd hook |
| `hooks/eva-pre-compact.ts` | 30 | PreCompact hook |

---

## v2.0.1 — 2026-02-09

### Bugfixes (found during verification testing)

- **NOT_EXPIRED coalesce**: Neo4j doesn't short-circuit OR, so `duration({days: NULL})` crashed. Fixed with `coalesce(m.decayDays, 36500)`.
- **Cypher `$query` param clash**: `session.run()` reserves `query` as first positional arg. Renamed to `$searchQuery` in `check_duplicates()` and `cmd_summarize()`.
- **ChromaDB post-filter**: Added `neo4j_filter_active_ids()` to batch-check ChromaDB results against Neo4j, filtering out expired/forgotten memories that ChromaDB doesn't know about.

---

## v2.0.0 — 2026-02-09

### Overview

Major feature upgrade adding confidence scoring, memory decay/expiration, automatic duplicate detection, supersedes chains, standing instruction injection, and four new tools. All changes are additive — no breaking changes to existing APIs.

### New Features

#### Confidence Scoring
- Every memory now carries a `confidence` field (0.0–1.0)
- Default: 0.8 (clearly communicated). 1.0 = explicitly stated, <0.5 = uncertain
- Auto-recall can filter by minimum confidence (`autoRecallMinConfidence` config)

#### Memory Decay / Expiration
- New `decayDays` field — memories expire after N days from creation
- Expired memories are automatically excluded from search and auto-recall
- Recommended: events/tasks 30–90 days, decisions/preferences permanent (null)

#### Duplicate Detection
- Automatic dedup before storing via `check_duplicates()`
- Primary: ChromaDB semantic similarity (>0.92 = skip, >0.5 = auto-supersede)
- Fallback: Neo4j fulltext BM25 scoring (same thresholds, normalized)
- Fail-open: if neither layer is available, the store proceeds normally

#### Supersedes Chains
- `supersedes` field links new memories to the ones they replace
- Creates `SUPERSEDES` relationship in Neo4j graph
- Old memory is automatically soft-deleted with reason "superseded by {newId}"

#### Standing Instructions
- New `instruction` memory type for "always do X" / "never do Y" rules
- Auto-classified from keywords: always, never, rule, guideline, policy, etc.
- Injected every turn via `<standing-instructions>` tags (before `<eva-memory>`)
- Configurable via `autoInjectInstructions` (default: true)

#### Source Provenance
- New `sourceChannel` and `sourceMessageId` fields for multi-channel tracing
- Track where memories originated (claude-code, discord, slack, web, etc.)

### New Tools

| Tool | Description |
|------|-------------|
| `eva_memory_update` | Modify existing memory content/metadata. Re-embeds in ChromaDB when content changes. |
| `eva_memory_forget` | Smart soft-delete by ID or search query (takes top match). Supports `reason` for audit trail. |
| `eva_memory_summarize` | Topic summary grouped by type. Optional topic/project filters. |
| `eva_memory_list` | Paginated browsing with sorting (created/importance/confidence/updated). |

### Updated Tools

| Tool | Changes |
|------|---------|
| `eva_memory_remember` | New params: `confidence`, `decayDays`, `supersedes`, `sourceChannel`, `sourceMessageId`. Handles duplicate skip/replace responses. |
| `eva_memory_search` | New param: `minConfidence`. |

### Schema Changes

5 new Neo4j indexes (all idempotent, backward compatible):
- `memory_confidence`, `memory_decayDays`, `memory_forgotten`
- `memory_sourceChannel`, `memory_type_created` (composite)

### Internal Changes

- `ACTIVE_MEMORY` constant replaces all scattered `NOT coalesce(m.forgotten, false)` with unified filter including decay expiration
- `neo4j_forget_with_reason()` stores `deleteReason` for audit trail
- `chroma_upsert()` helper for re-embedding on content update
- `cmd_evolve()` is now a backward-compatible alias for `cmd_update()`
- `cmd_maintain()` now stores `deleteReason = 'maintenance-pruned'`
- Auto-recall excludes `instruction` type from importance-based recall (instructions go in their own block)
- `openclaw.plugin.json` created with full config schema and UI hints

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `schema/init.cypher` | +10 | 5 new indexes |
| `scripts/memory.py` | +463 | New functions, commands, filters, dedup |
| `plugin/index.ts` | +349 | 4 new tools, updated auto-recall, new config |
| `plugin/openclaw.plugin.json` | +70 | New file — plugin metadata and config schema |
| `SKILL.md` | +72 | Full v2 documentation |

---

## v1.0.0 — 2026-02-08

Initial release. Three-layer memory system (markdown + Neo4j + ChromaDB/Ollama) with WAL crash safety, auto-recall injection, and session lifecycle management.
