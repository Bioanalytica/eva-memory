#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["neo4j>=5.0.0"]
# ///
"""
Eva Memory - Core Engine

Three-layer memory orchestrator: Markdown (always) + Neo4j (graph) + ChromaDB (optional semantic).
Designed for crash-safe operation with WAL protocol and graceful offline degradation.

Usage: python3 memory.py <command> [json_args]

Commands:
  remember         - Store a memory (WAL -> markdown -> Neo4j -> ChromaDB/queue)
  search           - Search across all layers
  auto-recall      - Fast injection for per-turn context (~20ms, Neo4j only)
  sync-start       - Initialize session, drain queue, load overview
  sync-end         - Close session, write summary
  pre-compaction-flush - Snapshot + flush WAL before context loss
  drain-queue      - Process pending ChromaDB embeddings
  recall           - Retrieve specific memories by ID or filter
  forget           - Smart soft-delete by id or query, with reason
  evolve           - Alias for update (backward compat)
  update           - Update existing memory content/metadata, re-embed in ChromaDB
  summarize        - Summarize memories by topic, grouped by type
  list             - Paginated browse with sorting
  instructions     - List active standing instructions
  entities         - List known entities and their connections
  maintain         - Run maintenance (compact daily logs, prune low-importance)

Env vars:
  EVA_NEO4J_URI    - bolt://neo4j:7687
  EVA_NEO4J_PASS   - Neo4j password
  EVA_STORE_PATH   - ~/.eva-memory (default)
  EVA_CHROMA_URL   - ChromaDB URL (optional)
  EVA_OLLAMA_URL   - Ollama URL (optional)
  EVA_CHROMA_COLLECTION - ChromaDB collection ID (optional)
  EVA_OLLAMA_MODEL - Embedding model (default: nomic-embed-text)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

# Neo4j is the only hard dependency (inline script metadata for uv run)
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError

# =============================================================================
# Configuration
# =============================================================================

NEO4J_URI = os.environ.get("EVA_NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("EVA_NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("EVA_NEO4J_PASS") or os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DB = "neo4j"

STORE_PATH = Path(os.environ.get("EVA_STORE_PATH", os.path.expanduser("~/.eva-memory")))
CHROMA_URL = os.environ.get("EVA_CHROMA_URL", "")
OLLAMA_URL = os.environ.get("EVA_OLLAMA_URL", "")
CHROMA_COLLECTION = os.environ.get("EVA_CHROMA_COLLECTION", "")
OLLAMA_MODEL = os.environ.get("EVA_OLLAMA_MODEL", "nomic-embed-text")
CLIENT_ID = os.environ.get("EVA_CLIENT_ID", "")  # Isolates session state per client

# Client-specific state files prevent concurrent client interference
_state_suffix = f"-{CLIENT_ID}" if CLIENT_ID else ""
QUEUE_PATH = STORE_PATH / "queue" / f"pending-embeddings{_state_suffix}.jsonl"
STATE_PATH = STORE_PATH / f"state{_state_suffix}.json"
CONFIG_PATH = STORE_PATH / "config.json"
SESSION_STATE_PATH = STORE_PATH / f"SESSION-STATE{_state_suffix}.md"
MEMORY_MD_PATH = STORE_PATH / "MEMORY.md"
DAILY_DIR = STORE_PATH / "daily"
PROJECTS_DIR = STORE_PATH / "projects"
BACKUPS_DIR = STORE_PATH / "backups" / "pre-compaction"

HEALTH_CHECK_TIMEOUT_MS = 500
MAX_QUEUE_FAILURES = 10

# Active memory filter (excludes forgotten + expired memories)
NOT_FORGOTTEN = "NOT coalesce(m.forgotten, false)"
NOT_EXPIRED = "(m.decayDays IS NULL OR datetime(m.created) + duration({days: coalesce(m.decayDays, 36500)}) > datetime())"
ACTIVE_MEMORY = f"{NOT_FORGOTTEN} AND {NOT_EXPIRED}"

# =============================================================================
# Entity Extraction (ported from git-notes-memory)
# =============================================================================

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "also", "now", "and",
    "but", "if", "or", "because", "until", "while", "this", "that", "these",
    "those", "it", "its", "i", "me", "my", "we", "our", "you", "your",
    "he", "him", "his", "she", "her", "they", "them", "their", "what",
    "which", "who", "whom", "get", "got", "about", "like", "want", "know",
    "think", "make", "take", "see", "come", "go", "use", "using", "used",
}


def extract_entities(content: Any) -> list[str]:
    """Extract key topics/entities from any content (domain-agnostic)."""
    priority_entities: list[str] = []
    generic_entities: set[str] = set()

    if isinstance(content, dict):
        topic_fields = [
            "topic", "about", "subject", "name", "title", "category",
            "area", "domain", "field", "concept", "item", "what",
            "learning", "studying", "project", "goal", "target",
        ]
        for k in topic_fields:
            if k in content and isinstance(content[k], str):
                val = content[k].lower().strip()
                priority_entities.append(val)
                if "." in val:
                    priority_entities.append(val.rsplit(".", 1)[0])

        list_fields = ["topics", "tags", "categories", "items", "subjects", "areas"]
        for k in list_fields:
            if k in content and isinstance(content[k], list):
                for item in content[k]:
                    if isinstance(item, str):
                        priority_entities.append(item.lower().strip())

        text = json.dumps(content).lower()
    else:
        text = str(content).lower()

    # Extract hashtags
    hashtags = re.findall(r"#(\w+)", text)
    generic_entities.update(h.lower() for h in hashtags)

    # Extract quoted phrases
    quoted = re.findall(r'"([^"]{2,30})"', text)
    generic_entities.update(q.lower().strip() for q in quoted if len(q.split()) <= 4)

    # Extract capitalized phrases
    caps = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", str(content) if not isinstance(content, dict) else json.dumps(content))
    generic_entities.update(c.lower() for c in caps if c.lower() not in STOP_WORDS)

    # Extract key terms
    words = re.findall(r"\b([a-z]{3,})\b", text)
    for word in words:
        if word not in STOP_WORDS and 3 <= len(word) <= 20:
            generic_entities.add(word)

    # Extract bigrams
    bigrams = re.findall(r"\b([a-z]{3,}\s+[a-z]{3,})\b", text)
    for bg in bigrams:
        parts = bg.split()
        if all(p not in STOP_WORDS for p in parts):
            generic_entities.add(bg)

    generic_entities = {e for e in generic_entities if len(e) >= 3 and e not in STOP_WORDS}
    sorted_generic = sorted(generic_entities, key=lambda x: (len(x.split()), len(x)))

    # Combine: priority first (deduplicated), then generic
    seen: set[str] = set()
    result: list[str] = []
    for e in priority_entities:
        if e and e not in seen and len(e) >= 3:
            seen.add(e)
            result.append(e)
    for e in sorted_generic:
        if e not in seen:
            seen.add(e)
            result.append(e)

    return result[:15]


def classify_memory(content: Any) -> str:
    """Classify memory type (domain-agnostic)."""
    if isinstance(content, dict):
        if "type" in content and isinstance(content["type"], str):
            return content["type"][:20]
        text = json.dumps(content).lower()
    else:
        text = str(content).lower()

    classifiers = [
        ("instruction", ["always", "never", "rule", "instruction", "standing order", "must always", "must never", "guideline", "policy"]),
        ("decision", ["decided", "decision", "chose", "choice", "picked", "selected", "going with", "will use", "opted"]),
        ("preference", ["prefer", "preference", "favorite", "like best", "rather", "better to", "style"]),
        ("learning", ["learned", "learning", "studied", "studying", "understood", "realized", "discovered", "insight"]),
        ("task", ["todo", "task", "need to", "should", "must", "will do", "plan to", "going to", "next step"]),
        ("question", ["question", "wondering", "curious", "ask about", "find out", "research", "investigate"]),
        ("note", ["note", "noticed", "observed", "important", "remember that", "keep in mind"]),
        ("progress", ["completed", "finished", "done", "progress", "achieved", "accomplished", "milestone"]),
    ]

    for label, keywords in classifiers:
        if any(w in text for w in keywords):
            return label

    return "info"


# =============================================================================
# State Management
# =============================================================================

def load_state() -> dict:
    """Load runtime state from disk."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "wal": {"pending": [], "lastFlush": None},
        "session": {"id": None, "startedAt": None, "project": None, "branch": None},
        "queue": {"pendingCount": 0, "consecutiveFailures": 0, "lastDrainAttempt": None, "lastSuccess": None},
        "stats": {"totalMemories": 0, "totalRecalls": 0, "totalSearches": 0, "lastMemoryAt": None},
    }


def save_state(state: dict) -> None:
    """Persist runtime state to disk."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def load_config() -> dict:
    """Load central config."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# =============================================================================
# Neo4j Layer
# =============================================================================

_driver = None


def get_driver():
    """Get or create Neo4j driver (singleton)."""
    global _driver
    if _driver is None:
        if not NEO4J_PASS:
            return None
        try:
            _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
            _driver.verify_connectivity()
        except (ServiceUnavailable, AuthError, Exception) as e:
            _driver = None
            log_warn(f"Neo4j unavailable: {e}")
            return None
    return _driver


def neo4j_store(memory: dict) -> bool:
    """Store a memory node and its entity/tag relationships in Neo4j."""
    driver = get_driver()
    if not driver:
        return False

    try:
        with driver.session(database=NEO4J_DB) as session:
            # Create memory node
            session.run(
                """
                MERGE (m:Memory {id: $id})
                SET m.content = $content,
                    m.summary = $summary,
                    m.type = $type,
                    m.importance = $importance,
                    m.project = $project,
                    m.created = $created,
                    m.updated = $updated,
                    m.sessionId = $sessionId,
                    m.source = $source,
                    m.confidence = $confidence,
                    m.decayDays = $decayDays,
                    m.sourceChannel = $sourceChannel,
                    m.sourceMessageId = $sourceMessageId
                """,
                id=memory["id"],
                content=memory.get("content", ""),
                summary=memory.get("summary", ""),
                type=memory.get("type", "info"),
                importance=memory.get("importance", 5),
                project=memory.get("project"),
                created=memory.get("created"),
                updated=memory.get("updated"),
                sessionId=memory.get("sessionId"),
                source=memory.get("source", "agent"),
                confidence=memory.get("confidence"),
                decayDays=memory.get("decayDays"),
                sourceChannel=memory.get("sourceChannel"),
                sourceMessageId=memory.get("sourceMessageId"),
            )

            # Handle supersedes chain
            if memory.get("supersedes"):
                session.run(
                    """
                    MATCH (m:Memory {id: $newId}), (old:Memory {id: $oldId})
                    MERGE (m)-[:SUPERSEDES]->(old)
                    SET old.forgotten = true, old.deleteReason = 'superseded by ' + $newId
                    """,
                    newId=memory["id"],
                    oldId=memory["supersedes"],
                )

            # Link entities
            for entity_name in memory.get("entities", []):
                session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    WITH e
                    MATCH (m:Memory {id: $memId})
                    MERGE (m)-[:MENTIONS]->(e)
                    """,
                    name=entity_name,
                    memId=memory["id"],
                )

            # Link tags
            for tag_name in memory.get("tags", []):
                session.run(
                    """
                    MERGE (t:Tag {name: $name})
                    WITH t
                    MATCH (m:Memory {id: $memId})
                    MERGE (m)-[:TAGGED]->(t)
                    """,
                    name=tag_name,
                    memId=memory["id"],
                )

            # Link project
            if memory.get("project"):
                session.run(
                    """
                    MERGE (p:Project {name: $name})
                    WITH p
                    MATCH (m:Memory {id: $memId})
                    MERGE (m)-[:BELONGS_TO]->(p)
                    """,
                    name=memory["project"],
                    memId=memory["id"],
                )

            # Link session
            if memory.get("sessionId"):
                session.run(
                    """
                    MERGE (s:Session {id: $sid})
                    WITH s
                    MATCH (m:Memory {id: $memId})
                    MERGE (m)-[:RECORDED_IN]->(s)
                    """,
                    sid=memory["sessionId"],
                    memId=memory["id"],
                )

        return True
    except Exception as e:
        log_warn(f"Neo4j store failed: {e}")
        return False


def neo4j_search(query: str, limit: int = 10, project: str | None = None, mem_type: str | None = None) -> list[dict]:
    """Search memories via Neo4j fulltext + entity matching."""
    driver = get_driver()
    if not driver:
        return []

    results = []
    try:
        with driver.session(database=NEO4J_DB) as session:
            # Fulltext search on content/summary
            cypher = f"""
                CALL db.index.fulltext.queryNodes('memory_fulltext', $searchQuery)
                YIELD node AS m, score
                WHERE ({ACTIVE_MEMORY})
                  AND ($project IS NULL OR m.project = $project)
                  AND ($type IS NULL OR m.type = $type)
                RETURN m.id AS id, m.content AS content, m.summary AS summary,
                       m.type AS type, m.importance AS importance,
                       m.project AS project, m.created AS created,
                       m.confidence AS confidence,
                       score
                ORDER BY score DESC, m.importance DESC
                LIMIT $limit
            """
            result = session.run(cypher, searchQuery=query, project=project, type=mem_type, limit=limit)
            for record in result:
                results.append({
                    "id": record["id"],
                    "content": record["content"],
                    "summary": record["summary"],
                    "type": record["type"],
                    "importance": record["importance"],
                    "confidence": record["confidence"],
                    "project": record["project"],
                    "created": record["created"],
                    "score": record["score"],
                    "source": "neo4j-fulltext",
                })

            # Entity-based search (find memories that mention entities matching query terms)
            entity_results = session.run(
                f"""
                CALL db.index.fulltext.queryNodes('entity_fulltext', $searchQuery)
                YIELD node AS entity, score AS entityScore
                WITH entity, entityScore
                MATCH (m:Memory)-[:MENTIONS]->(entity)
                WHERE ({ACTIVE_MEMORY})
                  AND ($project IS NULL OR m.project = $project)
                  AND ($type IS NULL OR m.type = $type)
                RETURN DISTINCT m.id AS id, m.content AS content, m.summary AS summary,
                       m.type AS type, m.importance AS importance,
                       m.project AS project, m.created AS created,
                       entityScore * 0.8 AS score
                ORDER BY score DESC
                LIMIT $limit
                """,
                searchQuery=query, project=project, type=mem_type, limit=limit,
            )
            seen_ids = {r["id"] for r in results}
            for record in entity_results:
                if record["id"] not in seen_ids:
                    results.append({
                        "id": record["id"],
                        "content": record["content"],
                        "summary": record["summary"],
                        "type": record["type"],
                        "importance": record["importance"],
                        "project": record["project"],
                        "created": record["created"],
                        "score": record["score"],
                        "source": "neo4j-entity",
                    })

    except Exception as e:
        log_warn(f"Neo4j search failed: {e}")

    return results


def neo4j_auto_recall(project: str | None = None, min_importance: int = 3, limit: int = 5) -> list[dict]:
    """Fast path: get high-importance recent memories for context injection."""
    driver = get_driver()
    if not driver:
        return []

    try:
        with driver.session(database=NEO4J_DB) as session:
            result = session.run(
                f"""
                MATCH (m:Memory)
                WHERE {ACTIVE_MEMORY}
                  AND m.importance >= $minImp
                  AND m.type <> 'instruction'
                  AND ($project IS NULL OR m.project = $project)
                RETURN m.id AS id, m.content AS content, m.summary AS summary,
                       m.type AS type, m.importance AS importance,
                       m.confidence AS confidence,
                       m.project AS project, m.created AS created
                ORDER BY m.importance DESC, m.created DESC
                LIMIT $limit
                """,
                minImp=min_importance, project=project, limit=limit,
            )
            return [dict(record) for record in result]
    except Exception as e:
        log_warn(f"Neo4j auto-recall failed: {e}")
        return []


def neo4j_get_entities(limit: int = 50) -> list[dict]:
    """List entities and their memory counts."""
    driver = get_driver()
    if not driver:
        return []

    try:
        with driver.session(database=NEO4J_DB) as session:
            result = session.run(
                """
                MATCH (e:Entity)<-[:MENTIONS]-(m:Memory)
                RETURN e.name AS name, count(m) AS memoryCount,
                       collect(DISTINCT m.type)[..5] AS types
                ORDER BY memoryCount DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(r) for r in result]
    except Exception as e:
        log_warn(f"Neo4j entities failed: {e}")
        return []


def neo4j_forget(memory_id: str) -> bool:
    """Soft-delete a memory (mark as forgotten, remove from search)."""
    driver = get_driver()
    if not driver:
        return False

    try:
        with driver.session(database=NEO4J_DB) as session:
            session.run(
                """
                MATCH (m:Memory {id: $id})
                SET m.forgotten = true, m.forgottenAt = $now
                REMOVE m.content, m.summary
                """,
                id=memory_id, now=now_iso(),
            )
        return True
    except Exception as e:
        log_warn(f"Neo4j forget failed: {e}")
        return False


def neo4j_evolve(memory_id: str, updates: dict) -> bool:
    """Update an existing memory's content or metadata."""
    driver = get_driver()
    if not driver:
        return False

    try:
        with driver.session(database=NEO4J_DB) as session:
            set_clauses = ["m.updated = $now"]
            params: dict[str, Any] = {"id": memory_id, "now": now_iso()}

            for key in ("content", "summary", "type", "importance", "project", "confidence", "decayDays"):
                if key in updates:
                    set_clauses.append(f"m.{key} = ${key}")
                    params[key] = updates[key]

            cypher = f"MATCH (m:Memory {{id: $id}}) SET {', '.join(set_clauses)}"
            session.run(cypher, **params)

            # Update entities if content changed
            if "content" in updates:
                new_entities = extract_entities(updates["content"])
                for ename in new_entities:
                    session.run(
                        """
                        MERGE (e:Entity {name: $name})
                        WITH e
                        MATCH (m:Memory {id: $memId})
                        MERGE (m)-[:MENTIONS]->(e)
                        """,
                        name=ename, memId=memory_id,
                    )

        return True
    except Exception as e:
        log_warn(f"Neo4j evolve failed: {e}")
        return False


def neo4j_filter_active_ids(ids: list[str]) -> set[str]:
    """Return the subset of IDs that are active (not forgotten, not expired)."""
    if not ids:
        return set()
    driver = get_driver()
    if not driver:
        return set(ids)  # fail-open: assume all active if Neo4j unavailable

    try:
        with driver.session(database=NEO4J_DB) as session:
            result = session.run(
                f"""
                MATCH (m:Memory)
                WHERE m.id IN $ids AND {ACTIVE_MEMORY}
                RETURN m.id AS id
                """,
                ids=ids,
            )
            return {r["id"] for r in result}
    except Exception:
        return set(ids)  # fail-open


def neo4j_get_instructions(project: str | None = None) -> list[dict]:
    """Fetch all active instruction-type memories, ordered by importance DESC."""
    driver = get_driver()
    if not driver:
        return []

    try:
        with driver.session(database=NEO4J_DB) as session:
            result = session.run(
                f"""
                MATCH (m:Memory)
                WHERE m.type = 'instruction'
                  AND {ACTIVE_MEMORY}
                  AND ($project IS NULL OR m.project = $project)
                RETURN m.id AS id, m.content AS content, m.summary AS summary,
                       m.importance AS importance, m.confidence AS confidence,
                       m.project AS project, m.created AS created
                ORDER BY m.importance DESC
                """,
                project=project,
            )
            return [dict(r) for r in result]
    except Exception as e:
        log_warn(f"Neo4j get instructions failed: {e}")
        return []


def neo4j_forget_with_reason(memory_id: str, reason: str | None = None) -> bool:
    """Soft-delete a memory with optional reason for audit trail."""
    driver = get_driver()
    if not driver:
        return False

    try:
        with driver.session(database=NEO4J_DB) as session:
            session.run(
                """
                MATCH (m:Memory {id: $id})
                SET m.forgotten = true, m.forgottenAt = $now, m.deleteReason = $reason
                REMOVE m.content, m.summary
                """,
                id=memory_id, now=now_iso(), reason=reason,
            )
        return True
    except Exception as e:
        log_warn(f"Neo4j forget failed: {e}")
        return False


# =============================================================================
# Markdown Layer (always available)
# =============================================================================

def markdown_store(memory: dict) -> bool:
    """Append memory to daily markdown log."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_file = DAILY_DIR / f"{today}.md"
        DAILY_DIR.mkdir(parents=True, exist_ok=True)

        if not daily_file.exists():
            daily_file.write_text(f"# Memory Log: {today}\n\n")

        importance_stars = "*" * memory.get("importance", 5)
        entry = (
            f"## [{memory.get('type', 'info').upper()}] {memory.get('summary', '')}\n"
            f"- **ID:** `{memory['id']}`\n"
            f"- **Importance:** {importance_stars} ({memory.get('importance', 5)}/10)\n"
            f"- **Time:** {memory.get('created', now_iso())}\n"
        )
        if memory.get("project"):
            entry += f"- **Project:** {memory['project']}\n"
        if memory.get("entities"):
            entry += f"- **Entities:** {', '.join(memory['entities'][:8])}\n"
        if memory.get("tags"):
            entry += f"- **Tags:** {', '.join('#' + t for t in memory['tags'])}\n"
        if memory.get("confidence") is not None:
            entry += f"- **Confidence:** {memory['confidence']}\n"
        if memory.get("decayDays") is not None:
            entry += f"- **Expires:** {memory['decayDays']} days\n"
        if memory.get("supersedes"):
            entry += f"- **Supersedes:** `{memory['supersedes']}`\n"
        if memory.get("sourceChannel"):
            entry += f"- **Source:** {memory['sourceChannel']}"
            if memory.get("sourceMessageId"):
                entry += f" ({memory['sourceMessageId']})"
            entry += "\n"
        if memory.get("deleteReason"):
            entry += f"- **Delete Reason:** {memory['deleteReason']}\n"
        entry += f"\n{memory.get('content', '')}\n\n---\n\n"

        with open(daily_file, "a") as f:
            f.write(entry)

        # Also write to project file if project is specified
        if memory.get("project"):
            project_file = PROJECTS_DIR / f"{memory['project']}.md"
            PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            if not project_file.exists():
                project_file.write_text(f"# Project: {memory['project']}\n\n")
            with open(project_file, "a") as f:
                f.write(entry)

        return True
    except Exception as e:
        log_warn(f"Markdown store failed: {e}")
        return False


# =============================================================================
# ChromaDB Layer (optional, with offline queue)
# =============================================================================

def chroma_health_check() -> bool:
    """Quick health check for ChromaDB availability."""
    if not CHROMA_URL:
        return False
    try:
        req = Request(f"{CHROMA_URL}/api/v2/heartbeat", method="GET")
        resp = urlopen(req, timeout=HEALTH_CHECK_TIMEOUT_MS / 1000)
        return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def ollama_embed(text: str) -> list[float] | None:
    """Get embedding from Ollama. Returns None if unavailable."""
    if not OLLAMA_URL:
        return None
    try:
        data = json.dumps({"model": OLLAMA_MODEL, "input": text}).encode()
        req = Request(
            f"{OLLAMA_URL}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urlopen(req, timeout=10)
        result = json.loads(resp.read())
        embeddings = result.get("embeddings")
        return embeddings[0] if embeddings else None
    except (URLError, OSError, TimeoutError, json.JSONDecodeError, IndexError):
        return None


def chroma_store(memory: dict, embedding: list[float]) -> bool:
    """Store memory in ChromaDB with pre-computed embedding."""
    if not CHROMA_URL or not CHROMA_COLLECTION:
        return False
    try:
        meta = {
            "type": memory.get("type", "info"),
            "importance": str(memory.get("importance", 5)),
            "project": memory.get("project") or None,
            "created": memory.get("created") or None,
            "summary": memory.get("summary") or None,
        }
        # ChromaDB rejects empty strings and None in metadata
        meta = {k: v for k, v in meta.items() if v}
        data = json.dumps({
            "ids": [memory["id"]],
            "embeddings": [embedding],
            "documents": [memory.get("content", "")],
            "metadatas": [meta],
        }).encode()
        url = f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections/{CHROMA_COLLECTION}/add"
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        resp = urlopen(req, timeout=10)
        return resp.status in (200, 201)
    except (URLError, OSError, TimeoutError):
        return False


def chroma_search(query: str, limit: int = 5) -> list[dict]:
    """Semantic search via ChromaDB. Returns empty list if unavailable."""
    if not CHROMA_URL or not CHROMA_COLLECTION:
        return []

    embedding = ollama_embed(query)
    if not embedding:
        return []

    try:
        data = json.dumps({
            "query_embeddings": [embedding],
            "n_results": limit,
            "include": ["documents", "metadatas", "distances"],
        }).encode()
        url = f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections/{CHROMA_COLLECTION}/query"
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        resp = urlopen(req, timeout=10)
        result = json.loads(resp.read())

        if not result.get("ids") or not result["ids"][0]:
            return []

        results = []
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result.get("distances") else 1.0
            # L2 distance: 0 = identical, larger = less similar
            # Convert to 0-1 similarity score
            score = 1 / (1 + distance)
            if score < 0.15:
                continue
            results.append({
                "id": doc_id,
                "content": result["documents"][0][i] if result.get("documents") else "",
                "score": score,
                "source": "chromadb-semantic",
                **{k: v for k, v in (result.get("metadatas", [[]])[0][i] or {}).items()},
            })
        return results
    except (URLError, OSError, TimeoutError, json.JSONDecodeError):
        return []


def chroma_upsert(memory_id: str, content: str, metadata: dict | None = None) -> bool:
    """Re-embed and update an existing document in ChromaDB."""
    if not CHROMA_URL or not CHROMA_COLLECTION:
        return False

    embedding = ollama_embed(content)
    if not embedding:
        return False

    try:
        meta = metadata or {}
        meta = {k: v for k, v in meta.items() if v}
        payload = {
            "ids": [memory_id],
            "embeddings": [embedding],
            "documents": [content],
        }
        if meta:
            payload["metadatas"] = [meta]
        data = json.dumps(payload).encode()
        url = f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections/{CHROMA_COLLECTION}/update"
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        resp = urlopen(req, timeout=10)
        return resp.status in (200, 201)
    except (URLError, OSError, TimeoutError):
        return False


def check_duplicates(content: str, mem_type: str, project: str | None = None) -> dict:
    """Check for duplicate/similar memories. Returns {action, existingId, similarity}."""
    # Primary: ChromaDB semantic similarity
    if CHROMA_URL and CHROMA_COLLECTION and OLLAMA_URL:
        embedding = ollama_embed(content)
        if embedding:
            try:
                where_filter = {"type": mem_type} if mem_type else None
                payload: dict[str, Any] = {
                    "query_embeddings": [embedding],
                    "n_results": 1,
                    "include": ["distances", "metadatas"],
                }
                if where_filter:
                    payload["where"] = where_filter
                data_bytes = json.dumps(payload).encode()
                url = f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections/{CHROMA_COLLECTION}/query"
                req = Request(url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
                resp = urlopen(req, timeout=10)
                result = json.loads(resp.read())

                if result.get("ids") and result["ids"][0]:
                    distance = result["distances"][0][0] if result.get("distances") else 999
                    similarity = 1 / (1 + distance)
                    existing_id = result["ids"][0][0]

                    if similarity > 0.92:
                        return {"action": "skip", "existingId": existing_id, "similarity": similarity}
                    if similarity > 0.5:
                        return {"action": "replace", "existingId": existing_id, "similarity": similarity}
            except (URLError, OSError, TimeoutError, json.JSONDecodeError, IndexError, KeyError):
                pass

    # Fallback: Neo4j fulltext search
    driver = get_driver()
    if driver:
        try:
            # Escape special Lucene characters for fulltext search
            safe_query = re.sub(r'([+\-&|!(){}[\]^"~*?:\\/])', r'\\\1', content[:200])
            if not safe_query.strip():
                return {"action": "allow"}
            with driver.session(database=NEO4J_DB) as session:
                result = session.run(
                    f"""
                    CALL db.index.fulltext.queryNodes('memory_fulltext', $searchQuery)
                    YIELD node AS m, score
                    WHERE {ACTIVE_MEMORY}
                      AND ($type IS NULL OR m.type = $type)
                    RETURN m.id AS id, score
                    ORDER BY score DESC
                    LIMIT 1
                    """,
                    searchQuery=safe_query, type=mem_type,
                )
                record = result.single()
                if record:
                    # BM25 scores vary widely; normalize roughly
                    score = record["score"]
                    if score > 8.0:
                        return {"action": "skip", "existingId": record["id"], "similarity": min(score / 10, 1.0)}
                    if score > 4.0:
                        return {"action": "replace", "existingId": record["id"], "similarity": score / 10}
        except Exception:
            pass

    # Fail-open: allow the store
    return {"action": "allow"}


def queue_for_embedding(memory: dict) -> None:
    """Append memory to offline queue for later ChromaDB processing."""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": memory["id"],
        "content": memory.get("content", ""),
        "metadata": {
            "type": memory.get("type", "info"),
            "importance": str(memory.get("importance", 5)),
            "project": memory.get("project", ""),
            "created": memory.get("created", ""),
            "summary": memory.get("summary", ""),
        },
        "queuedAt": now_iso(),
    }
    with open(QUEUE_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def drain_queue() -> dict:
    """Process pending ChromaDB embeddings from the JSONL queue."""
    if not QUEUE_PATH.exists():
        return {"processed": 0, "remaining": 0, "status": "empty"}

    lines = QUEUE_PATH.read_text().strip().split("\n")
    lines = [l for l in lines if l.strip()]
    if not lines:
        return {"processed": 0, "remaining": 0, "status": "empty"}

    state = load_state()
    if state["queue"]["consecutiveFailures"] >= MAX_QUEUE_FAILURES:
        return {"processed": 0, "remaining": len(lines), "status": "skipped-max-failures"}

    if not chroma_health_check():
        state["queue"]["consecutiveFailures"] += 1
        state["queue"]["lastDrainAttempt"] = now_iso()
        save_state(state)
        return {"processed": 0, "remaining": len(lines), "status": "chromadb-offline"}

    processed = 0
    remaining_lines = []

    for line in lines:
        try:
            entry = json.loads(line)
            embedding = ollama_embed(entry["content"])
            if not embedding:
                remaining_lines.append(line)
                continue

            stored = chroma_store(
                {"id": entry["id"], "content": entry["content"], **entry.get("metadata", {})},
                embedding,
            )
            if stored:
                processed += 1
            else:
                remaining_lines.append(line)
        except (json.JSONDecodeError, KeyError):
            # Skip malformed entries
            continue

    # Rewrite queue with remaining entries
    if remaining_lines:
        QUEUE_PATH.write_text("\n".join(remaining_lines) + "\n")
    else:
        QUEUE_PATH.write_text("")

    state["queue"]["consecutiveFailures"] = 0
    state["queue"]["lastSuccess"] = now_iso()
    state["queue"]["lastDrainAttempt"] = now_iso()
    state["queue"]["pendingCount"] = len(remaining_lines)
    save_state(state)

    return {"processed": processed, "remaining": len(remaining_lines), "status": "ok"}


# =============================================================================
# WAL (Write-Ahead Log) Protocol
# =============================================================================

def wal_write(memory: dict) -> None:
    """Write memory to WAL before any other storage."""
    state = load_state()
    state["wal"]["pending"].append(memory)
    save_state(state)


def wal_flush(memory_id: str) -> None:
    """Remove a memory from WAL after successful storage."""
    state = load_state()
    state["wal"]["pending"] = [m for m in state["wal"]["pending"] if m.get("id") != memory_id]
    state["wal"]["lastFlush"] = now_iso()
    save_state(state)


def wal_recover() -> list[dict]:
    """Get any pending WAL entries (crash recovery)."""
    state = load_state()
    return state["wal"]["pending"]


# =============================================================================
# Commands
# =============================================================================

def cmd_remember(args: dict) -> dict:
    """Store a memory through all layers with WAL safety."""
    content = args.get("content", "")
    if not content:
        return {"error": "content is required"}

    memory_type = args.get("type") or classify_memory(content)
    importance = args.get("importance", 5)
    project = args.get("project")
    tags = args.get("tags", [])
    summary = args.get("summary", content[:200])
    entities = args.get("entities") or extract_entities(content)

    state = load_state()
    session_id = state["session"]["id"]

    confidence = args.get("confidence", 0.8)
    decay_days = args.get("decayDays")
    supersedes = args.get("supersedes")
    source_channel = args.get("sourceChannel")
    source_message_id = args.get("sourceMessageId")

    memory = {
        "id": str(uuid.uuid4()),
        "content": content,
        "summary": summary,
        "type": memory_type,
        "importance": int(importance),
        "confidence": float(confidence),
        "decayDays": int(decay_days) if decay_days is not None else None,
        "supersedes": supersedes,
        "project": project,
        "tags": tags,
        "entities": entities,
        "created": now_iso(),
        "updated": now_iso(),
        "sessionId": session_id,
        "source": args.get("source", "agent"),
        "sourceChannel": source_channel,
        "sourceMessageId": source_message_id,
    }

    # Duplicate detection (before WAL write)
    dup = check_duplicates(content, memory_type, project)
    if dup["action"] == "skip":
        return {"skipped": True, "existingId": dup["existingId"], "similarity": dup.get("similarity")}
    if dup["action"] == "replace":
        memory["supersedes"] = dup["existingId"]

    # WAL first (crash safety)
    wal_write(memory)

    # Layer 1: Markdown (always)
    md_ok = markdown_store(memory)

    # Layer 2: Neo4j (graph)
    neo_ok = neo4j_store(memory)

    # Layer 3: ChromaDB (semantic, or queue)
    chroma_ok = False
    queued = False
    if CHROMA_URL and OLLAMA_URL:
        embedding = ollama_embed(content)
        if embedding:
            chroma_ok = chroma_store(memory, embedding)
        if not chroma_ok:
            queue_for_embedding(memory)
            queued = True
    elif CHROMA_URL:
        queue_for_embedding(memory)
        queued = True

    # Flush WAL after successful storage
    if md_ok or neo_ok:
        wal_flush(memory["id"])

    # Update stats
    state = load_state()
    state["stats"]["totalMemories"] += 1
    state["stats"]["lastMemoryAt"] = now_iso()
    save_state(state)

    return {
        "id": memory["id"],
        "type": memory_type,
        "importance": importance,
        "confidence": confidence,
        "decayDays": decay_days,
        "supersedes": memory.get("supersedes"),
        "entities": entities[:5],
        "layers": {
            "markdown": md_ok,
            "neo4j": neo_ok,
            "chromadb": chroma_ok,
            "queued": queued,
        },
    }


def cmd_search(args: dict) -> dict:
    """Search across all layers and merge results."""
    query = args.get("query", "")
    if not query:
        return {"error": "query is required"}

    limit = args.get("limit", 10)
    project = args.get("project")
    mem_type = args.get("type")

    # Neo4j search (fulltext + entity)
    neo_results = neo4j_search(query, limit=limit, project=project, mem_type=mem_type)

    # ChromaDB semantic search (optional)
    chroma_results = chroma_search(query, limit=limit)

    # Post-filter ChromaDB results against Neo4j active status
    # (ChromaDB doesn't know about forgotten/expired memories)
    if chroma_results:
        chroma_ids = [r["id"] for r in chroma_results]
        active_ids = neo4j_filter_active_ids(chroma_ids)
        chroma_results = [r for r in chroma_results if r["id"] in active_ids]

    # Merge and deduplicate
    seen_ids: set[str] = set()
    merged: list[dict] = []

    for r in neo_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            merged.append(r)

    for r in chroma_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            merged.append(r)

    # Sort by score descending
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)

    state = load_state()
    state["stats"]["totalSearches"] += 1
    save_state(state)

    return {
        "results": merged[:limit],
        "count": len(merged),
        "sources": {
            "neo4j": len(neo_results),
            "chromadb": len(chroma_results),
        },
    }


def cmd_auto_recall(args: dict) -> dict:
    """Fast path for per-turn context injection. Neo4j only for speed."""
    project = args.get("project")
    min_importance = args.get("minImportance", 3)
    limit = args.get("limit", 5)

    memories = neo4j_auto_recall(project=project, min_importance=min_importance, limit=limit)
    instructions = neo4j_get_instructions(project=project)

    state = load_state()
    state["stats"]["totalRecalls"] += 1
    save_state(state)

    return {
        "memories": memories,
        "instructions": instructions,
        "count": len(memories),
    }


def cmd_sync_start(args: dict) -> dict:
    """Initialize a new session: recover WAL, drain queue, load overview."""
    session_id = args.get("sessionId") or str(uuid.uuid4())
    project = args.get("project")
    branch = args.get("branch")

    state = load_state()
    state["session"] = {
        "id": session_id,
        "startedAt": now_iso(),
        "project": project,
        "branch": branch,
    }
    save_state(state)

    # Recover any pending WAL entries
    pending = wal_recover()
    recovered = 0
    for memory in pending:
        md_ok = markdown_store(memory)
        neo_ok = neo4j_store(memory)
        if md_ok or neo_ok:
            wal_flush(memory["id"])
            recovered += 1

    # Try to drain ChromaDB queue
    drain_result = drain_queue()

    # Link session in Neo4j
    driver = get_driver()
    if driver:
        try:
            with driver.session(database=NEO4J_DB) as session:
                session.run(
                    """
                    MERGE (s:Session {id: $id})
                    SET s.startedAt = $start, s.project = $project, s.branch = $branch
                    """,
                    id=session_id, start=now_iso(), project=project, branch=branch,
                )
                if project:
                    session.run(
                        """
                        MERGE (p:Project {name: $name})
                        WITH p
                        MATCH (s:Session {id: $sid})
                        MERGE (s)-[:BELONGS_TO]->(p)
                        """,
                        name=project, sid=session_id,
                    )
        except Exception as e:
            log_warn(f"Neo4j session init failed: {e}")

    # Get overview stats
    overview = _get_overview(project)

    return {
        "sessionId": session_id,
        "walRecovered": recovered,
        "queueDrain": drain_result,
        "overview": overview,
    }


def cmd_sync_end(args: dict) -> dict:
    """Close current session with summary."""
    state = load_state()
    session_id = state["session"]["id"]
    summary = args.get("summary", "")

    if session_id:
        driver = get_driver()
        if driver:
            try:
                with driver.session(database=NEO4J_DB) as session:
                    session.run(
                        """
                        MATCH (s:Session {id: $id})
                        SET s.endedAt = $end, s.summary = $summary
                        """,
                        id=session_id, end=now_iso(), summary=summary,
                    )
            except Exception as e:
                log_warn(f"Neo4j session close failed: {e}")

    # Clear session state
    state["session"] = {"id": None, "startedAt": None, "project": None, "branch": None}
    save_state(state)

    # Reset session state markdown
    SESSION_STATE_PATH.write_text(
        "# Session State (Hot RAM)\n\n"
        "> Active working memory for the current session. Cleared on session reset.\n\n"
        "## Current Context\n\n\n## Active Tasks\n\n\n## Recent Decisions\n\n\n## Working Notes\n\n"
    )

    return {"sessionId": session_id, "closed": True}


def cmd_pre_compaction_flush(args: dict) -> dict:
    """Snapshot current state before context compaction."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUPS_DIR / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Copy current session state and memory
    files_backed = []
    for src in [SESSION_STATE_PATH, MEMORY_MD_PATH, STATE_PATH]:
        if src.exists():
            dest = backup_dir / src.name
            shutil.copy2(src, dest)
            files_backed.append(src.name)

    # Flush any WAL entries
    pending = wal_recover()
    flushed = 0
    for memory in pending:
        md_ok = markdown_store(memory)
        neo_ok = neo4j_store(memory)
        if md_ok or neo_ok:
            wal_flush(memory["id"])
            flushed += 1

    return {
        "backupDir": str(backup_dir),
        "filesBacked": files_backed,
        "walFlushed": flushed,
    }


def cmd_recall(args: dict) -> dict:
    """Retrieve specific memories by ID or filter criteria."""
    memory_id = args.get("id")
    mem_type = args.get("type")
    project = args.get("project")
    limit = args.get("limit", 10)

    driver = get_driver()
    if not driver:
        return {"error": "Neo4j unavailable", "results": []}

    try:
        with driver.session(database=NEO4J_DB) as session:
            if memory_id:
                result = session.run(
                    f"MATCH (m:Memory {{id: $id}}) WHERE {ACTIVE_MEMORY} RETURN m",
                    id=memory_id,
                )
                records = [dict(r["m"]) for r in result]
            else:
                result = session.run(
                    f"""
                    MATCH (m:Memory)
                    WHERE {ACTIVE_MEMORY}
                      AND ($type IS NULL OR m.type = $type)
                      AND ($project IS NULL OR m.project = $project)
                    RETURN m
                    ORDER BY m.created DESC
                    LIMIT $limit
                    """,
                    type=mem_type, project=project, limit=limit,
                )
                records = [dict(r["m"]) for r in result]
            return {"results": records, "count": len(records)}
    except Exception as e:
        return {"error": str(e), "results": []}


def cmd_forget(args: dict) -> dict:
    """Smart soft-delete: by id or by query (takes top match)."""
    memory_id = args.get("id")
    query = args.get("query")
    reason = args.get("reason")

    if not memory_id and not query:
        return {"error": "id or query is required"}

    # If query provided, search and take top match
    if not memory_id and query:
        results = neo4j_search(query, limit=1)
        if not results:
            return {"error": "no matching memory found", "query": query}
        memory_id = results[0]["id"]

    ok = neo4j_forget_with_reason(memory_id, reason)
    return {"id": memory_id, "forgotten": ok, "reason": reason}


def cmd_update(args: dict) -> dict:
    """Update an existing memory's content or metadata. Re-embeds in ChromaDB if content changes."""
    memory_id = args.get("id")
    if not memory_id:
        return {"error": "id is required"}

    updates = {k: v for k, v in args.items() if k in ("content", "summary", "type", "importance", "project", "confidence", "decayDays")}
    if not updates:
        return {"error": "no updates provided"}

    ok = neo4j_evolve(memory_id, updates)

    # Re-embed in ChromaDB if content changed
    if "content" in updates and ok:
        chroma_upsert(memory_id, updates["content"], {
            "type": updates.get("type", "info"),
            "importance": str(updates.get("importance", 5)),
            "project": updates.get("project") or args.get("project") or "",
            "summary": updates.get("summary", updates["content"][:200]),
        })

        # Also log to markdown
        markdown_store({
            "id": memory_id,
            "content": f"[UPDATED] {updates['content']}",
            "summary": updates.get("summary", updates["content"][:200]),
            "type": updates.get("type") or args.get("type", "update"),
            "importance": updates.get("importance") or args.get("importance", 5),
            "project": updates.get("project") or args.get("project"),
            "entities": extract_entities(updates["content"]),
            "tags": ["updated"],
            "created": now_iso(),
        })

    return {"id": memory_id, "updated": ok, "fields": list(updates.keys())}


def cmd_evolve(args: dict) -> dict:
    """Backward-compatible alias for cmd_update."""
    return cmd_update(args)


def cmd_summarize(args: dict) -> dict:
    """Summarize memories, optionally filtered by topic, grouped by type."""
    topic = args.get("topic")
    project = args.get("project")
    limit = args.get("limit", 50)

    driver = get_driver()
    if not driver:
        return {"error": "Neo4j unavailable", "groups": {}}

    try:
        with driver.session(database=NEO4J_DB) as session:
            if topic:
                # Escape special Lucene characters
                safe_topic = re.sub(r'([+\-&|!(){}[\]^"~*?:\\/])', r'\\\1', topic)
                if not safe_topic.strip():
                    return {"groups": {}, "totalCount": 0}
                result = session.run(
                    f"""
                    CALL db.index.fulltext.queryNodes('memory_fulltext', $searchQuery)
                    YIELD node AS m, score
                    WHERE {ACTIVE_MEMORY}
                      AND ($project IS NULL OR m.project = $project)
                    RETURN m.id AS id, m.content AS content, m.summary AS summary,
                           m.type AS type, m.importance AS importance,
                           m.confidence AS confidence, m.created AS created
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    searchQuery=safe_topic, project=project, limit=limit,
                )
            else:
                result = session.run(
                    f"""
                    MATCH (m:Memory)
                    WHERE {ACTIVE_MEMORY}
                      AND ($project IS NULL OR m.project = $project)
                    RETURN m.id AS id, m.content AS content, m.summary AS summary,
                           m.type AS type, m.importance AS importance,
                           m.confidence AS confidence, m.created AS created
                    ORDER BY m.importance DESC
                    LIMIT $limit
                    """,
                    project=project, limit=limit,
                )

            groups: dict[str, list[dict]] = {}
            total = 0
            for record in result:
                mem = dict(record)
                mem_type = mem.get("type", "info")
                if mem_type not in groups:
                    groups[mem_type] = []
                groups[mem_type].append(mem)
                total += 1

            return {"groups": groups, "totalCount": total}
    except Exception as e:
        return {"error": str(e), "groups": {}}


def cmd_list(args: dict) -> dict:
    """Paginated listing of memories with sorting."""
    page = args.get("page", 1)
    page_size = args.get("pageSize", 20)
    sort_by = args.get("sortBy", "created")
    sort_order = args.get("sortOrder", "DESC")
    project = args.get("project")
    mem_type = args.get("type")

    # Validate sort fields to prevent Cypher injection
    allowed_sorts = {"created", "importance", "confidence", "updated"}
    if sort_by not in allowed_sorts:
        sort_by = "created"
    if sort_order.upper() not in ("ASC", "DESC"):
        sort_order = "DESC"

    skip = (page - 1) * page_size

    driver = get_driver()
    if not driver:
        return {"error": "Neo4j unavailable", "results": [], "total": 0}

    try:
        with driver.session(database=NEO4J_DB) as session:
            # Get total count
            count_result = session.run(
                f"""
                MATCH (m:Memory)
                WHERE {ACTIVE_MEMORY}
                  AND ($type IS NULL OR m.type = $type)
                  AND ($project IS NULL OR m.project = $project)
                RETURN count(m) AS total
                """,
                type=mem_type, project=project,
            )
            total = count_result.single()["total"]

            # Get paginated results
            result = session.run(
                f"""
                MATCH (m:Memory)
                WHERE {ACTIVE_MEMORY}
                  AND ($type IS NULL OR m.type = $type)
                  AND ($project IS NULL OR m.project = $project)
                RETURN m.id AS id, m.content AS content, m.summary AS summary,
                       m.type AS type, m.importance AS importance,
                       m.confidence AS confidence, m.project AS project,
                       m.created AS created, m.updated AS updated,
                       m.decayDays AS decayDays
                ORDER BY m.{sort_by} {sort_order}
                SKIP $skip
                LIMIT $pageSize
                """,
                type=mem_type, project=project, skip=skip, pageSize=page_size,
            )
            records = [dict(r) for r in result]

            total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
            return {
                "results": records,
                "total": total,
                "page": page,
                "pageSize": page_size,
                "totalPages": total_pages,
            }
    except Exception as e:
        return {"error": str(e), "results": [], "total": 0}


def cmd_instructions(args: dict) -> dict:
    """Return all active standing instructions."""
    project = args.get("project")
    instructions = neo4j_get_instructions(project=project)
    return {"instructions": instructions, "count": len(instructions)}


def cmd_entities(args: dict) -> dict:
    """List known entities and their connection counts."""
    limit = args.get("limit", 50)
    entities = neo4j_get_entities(limit=limit)
    return {"entities": entities, "count": len(entities)}


def cmd_maintain(args: dict) -> dict:
    """Run maintenance: compact daily logs, prune old low-importance memories."""
    max_age_days = args.get("maxAgeDays", 90)
    min_importance = args.get("minImportance", 3)
    results = {"pruned": 0, "compacted": 0}

    driver = get_driver()
    if driver:
        try:
            cutoff = datetime.now(timezone.utc)
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

            with driver.session(database=NEO4J_DB) as session:
                # Soft-delete old, low-importance memories
                result = session.run(
                    f"""
                    MATCH (m:Memory)
                    WHERE m.importance < $minImp
                      AND m.created < $cutoff
                      AND {ACTIVE_MEMORY}
                    SET m.forgotten = true, m.forgottenAt = $now, m.deleteReason = 'maintenance-pruned'
                    REMOVE m.content, m.summary
                    RETURN count(m) AS pruned
                    """,
                    minImp=min_importance, cutoff=cutoff_str, now=now_iso(),
                )
                record = result.single()
                if record:
                    results["pruned"] = record["pruned"]
        except Exception as e:
            log_warn(f"Maintenance failed: {e}")

    return results


def cmd_drain_queue(args: dict) -> dict:
    """Manually trigger queue drain."""
    return drain_queue()


# =============================================================================
# Helpers
# =============================================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_overview(project: str | None = None) -> dict:
    """Get memory system overview stats."""
    driver = get_driver()
    overview = {"totalMemories": 0, "recentCount": 0, "topEntities": [], "projects": []}

    if driver:
        try:
            with driver.session(database=NEO4J_DB) as session:
                # Total memories
                result = session.run(
                    f"MATCH (m:Memory) WHERE {ACTIVE_MEMORY} RETURN count(m) AS total"
                )
                record = result.single()
                if record:
                    overview["totalMemories"] = record["total"]

                # Top entities
                result = session.run(
                    f"""
                    MATCH (e:Entity)<-[:MENTIONS]-(m:Memory)
                    WHERE {ACTIVE_MEMORY}
                    RETURN e.name AS name, count(m) AS count
                    ORDER BY count DESC
                    LIMIT 10
                    """,
                )
                overview["topEntities"] = [{"name": r["name"], "count": r["count"]} for r in result]

                # Projects
                result = session.run("MATCH (p:Project) RETURN p.name AS name ORDER BY p.name")
                overview["projects"] = [r["name"] for r in result]

        except Exception as e:
            log_warn(f"Overview query failed: {e}")

    # Queue stats
    if QUEUE_PATH.exists():
        try:
            lines = [l for l in QUEUE_PATH.read_text().strip().split("\n") if l.strip()]
            overview["pendingEmbeddings"] = len(lines)
        except OSError:
            pass

    return overview


def log_warn(msg: str) -> None:
    """Log warnings to stderr (not mixed with JSON stdout)."""
    print(f"[eva-memory WARN] {msg}", file=sys.stderr)


# =============================================================================
# Main CLI Dispatcher
# =============================================================================

COMMANDS = {
    "remember": cmd_remember,
    "search": cmd_search,
    "auto-recall": cmd_auto_recall,
    "sync-start": cmd_sync_start,
    "sync-end": cmd_sync_end,
    "pre-compaction-flush": cmd_pre_compaction_flush,
    "drain-queue": cmd_drain_queue,
    "recall": cmd_recall,
    "forget": cmd_forget,
    "evolve": cmd_evolve,
    "update": cmd_update,
    "summarize": cmd_summarize,
    "list": cmd_list,
    "instructions": cmd_instructions,
    "entities": cmd_entities,
    "maintain": cmd_maintain,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": f"Usage: memory.py <command> [json_args]\nCommands: {', '.join(COMMANDS.keys())}"}))
        sys.exit(1)

    command = sys.argv[1]
    if command not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {command}. Available: {', '.join(COMMANDS.keys())}"}))
        sys.exit(1)

    # Parse JSON args (from argv[2] or stdin)
    args: dict = {}
    if len(sys.argv) > 2:
        try:
            args = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON args: {e}"}))
            sys.exit(1)

    try:
        result = COMMANDS[command](args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        # Clean up Neo4j driver
        if _driver:
            try:
                _driver.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
