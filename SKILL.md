---
name: eva-memory
description: Comprehensive AI memory system. USE WHEN storing decisions, preferences, learnings, context, or recalling past interactions.
---

# Eva Memory System (Engram Vault Architecture)

Long-term memory across sessions with three storage layers: markdown (always), Neo4j graph (relationships), ChromaDB (semantic search, optional).

## Silent Operation (CRITICAL)

NEVER mention the memory system to the user. Memory operations happen invisibly:
- Do NOT say "I'll remember that" or "Let me check my memory"
- Do NOT reference memory tools, storage layers, or recall results
- Simply USE the information naturally, as if you already knew it
- When storing: just do it silently alongside your response
- When recalling: incorporate knowledge seamlessly into your answer

## Tools

### eva_memory_remember
> Claude Code: `mcp__eva-memory__remember`

Store important information. Use silently when you encounter:
- User preferences or decisions
- Project architecture choices
- Debugging patterns that worked
- Configuration details
- Workflow preferences
- Any "aha" moments or insights
- Standing instructions ("always do X", "never do Y")

### eva_memory_search
> Claude Code: `mcp__eva-memory__search`

Search past memories. Use when you need context about:
- Previous decisions on similar topics
- User preferences you might have stored
- Project history and evolution
- Past debugging sessions

### eva_memory_update
> Claude Code: `mcp__eva-memory__update`

Modify an existing memory (by ID). Use when:
- Information has changed or been corrected
- You need to adjust importance or confidence
- Content needs refinement or expansion
- Re-embeds in ChromaDB automatically when content changes

### eva_memory_forget
> Claude Code: `mcp__eva-memory__forget`

Smart soft-delete. Accepts either `id` (direct) or `query` (searches and takes top match). Always provide a `reason` for the audit trail. Use when:
- Information is no longer relevant
- User explicitly asks to forget something
- Correcting a mistaken memory

### eva_memory_summarize
> Claude Code: `mcp__eva-memory__summarize`

Get an overview of stored memories grouped by type. Optionally filter by `topic` or `project`. Use when:
- Getting a sense of what's been remembered
- Reviewing memories about a specific topic
- Auditing memory contents

### eva_memory_list
> Claude Code: `mcp__eva-memory__list`

Paginated browsing with sorting. Supports `sortBy` (created, importance, confidence, updated), `sortOrder` (ASC/DESC), and filters (`type`, `project`). Use for:
- Detailed memory inspection
- Finding specific memories to update or forget

### eva_memory_recall
> Claude Code: `mcp__eva-memory__recall`

Retrieve specific memories by ID or filter criteria. Supports `id` (single memory), `type` filter, `project` filter, and `limit`. Use when:
- You need a specific memory by ID
- Retrieving all memories of a certain type
- Getting project-scoped context

### eva_memory_instructions
> Claude Code: `mcp__eva-memory__instructions`

List all active standing instructions (`instruction`-type memories). Returns content and metadata for each. Use when:
- Reviewing what standing rules are active
- Checking if an instruction already exists before creating a new one
- Auditing active behavioral rules

### eva_memory_entities
> Claude Code: `mcp__eva-memory__entities`

List known entities and their graph connections. Shows entity names, types, and relationship counts. Use when:
- Exploring what topics/people/projects are in memory
- Understanding the knowledge graph structure
- Finding entity names for targeted searches

### eva_memory_maintain
> Claude Code: `mcp__eva-memory__maintain`

Run maintenance operations on the memory store. Prunes low-importance old memories, cleans up expired entries, and optimizes storage. Use when:
- Memory count is growing large
- Periodic cleanup is needed
- User requests memory maintenance

## What to Remember

**Always remember:**
- Explicit decisions ("I chose X over Y because...")
- Preferences ("I prefer TypeScript", "always use bun")
- Architecture choices and rationale
- Things the user corrected you on
- Project-specific conventions
- Debugging discoveries (root cause + fix)
- Standing instructions (rules, policies, "always/never" directives)

**Never remember:**
- Transient conversation filler
- Obvious facts (language syntax, common patterns)
- Temporary debugging output
- Secrets, tokens, passwords (NEVER store these)

## Importance Levels

| Level | Use For |
|-------|---------|
| 1-2   | Minor observations, fleeting notes |
| 3-4   | Useful context, general preferences |
| 5-6   | Important decisions, project conventions |
| 7-8   | Critical architecture choices, strong preferences |
| 9-10  | Permanent facts (user identity, core stack, non-negotiables) |

## Confidence Scoring

| Score | Meaning |
|-------|---------|
| 1.0   | Explicitly stated by the user |
| 0.8   | Default - clearly communicated |
| 0.5-0.7 | Inferred from context or behavior |
| < 0.5 | Uncertain, speculative |

Confidence is used to filter auto-recall results (configurable threshold) and helps prioritize which memories to trust when they conflict.

## Decay / Expiration

Use `decayDays` to set memory expiration:

| Memory Type | Recommended Decay |
|-------------|-------------------|
| Events, tasks, progress | 30-90 days |
| Questions, temporary notes | 14-30 days |
| Decisions, preferences | Permanent (omit/null) |
| Instructions | Permanent (omit/null) |
| Core identity, stack prefs | Permanent (omit/null) |

Expired memories are automatically excluded from search and auto-recall.

## Memory Types

- `instruction` - Standing orders, auto-injected every turn. Use for "always do X", "never do Y", user-specific rules, policies.
- `decision` - Choices made with rationale
- `preference` - User likes/dislikes, style choices
- `learning` - New knowledge, insights, discoveries
- `task` - TODOs, planned work
- `note` - General observations
- `progress` - Milestones, completions
- `question` - Open questions, research topics
- `info` - General information (default)

## Source Provenance

Use `sourceChannel` and `sourceMessageId` for multi-channel tracing:
- `sourceChannel`: origin (e.g. "claude-code", "discord", "slack", "web")
- `sourceMessageId`: message ID for back-reference

## Auto-Recall

The system automatically injects two blocks at session start:

Injected via the `SessionStart` hook (`eva-session-start.ts`):
1. Standing instructions block - All active instruction-type memories
2. Relevant context block - High-importance memories (fit to `EVA_RECALL_MAX_TOKENS` budget)
3. Output as `<system-reminder>` tag to stdout, which Claude Code injects into context
4. Re-injected on context compaction (hook fires again on compact events)

You don't need to manually search for context that was already injected via these mechanisms.

## Duplicate Detection

When storing a memory, the system automatically checks for duplicates:
- **>0.92 similarity**: skipped entirely (exact duplicate)
- **>0.5 similarity + same type**: auto-supersedes the old memory
- Uses ChromaDB semantic similarity when available, falls back to Neo4j fulltext
