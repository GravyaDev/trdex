---
name: persistent-memory-stack
description: "Bootstrap a production-grade 6-tier persistent memory architecture for AI agent systems. Includes PostgreSQL schema, pgvector semantic search, Python retrieval/writer templates, and adaptation notes for alternative stacks."
risk: low
source: gravya
date_added: "2026-04-05"
---

# Persistent Memory Stack — 6-Tier Architecture

## Purpose

Give an AI agent system durable, structured memory that survives session boundaries.
This skill bootstraps the full stack — DB schema, retrieval pipeline, writer pipeline, and nomination lifecycle — adapted to your project's context.

---

## Prerequisites

**Required (canonical stack):**
- PostgreSQL ≥ 14 with `pgvector` extension
- Python ≥ 3.11 (async)
- `psycopg` (psycopg3) async pool
- An embedding model accessible via LangChain embeddings interface (e.g. VoyageAI, OpenAI, Cohere)
- Optional but recommended: a reranker (e.g. Jina Reranker v3) for Tier 4 precision

**Alternative stacks — see Adaptation Notes at the bottom.**

---

## The 6 Tiers

| Tier | Name | Storage | Retrieval | Written by |
|------|------|---------|-----------|-----------|
| 1 | Pinned Directives | DB table | Always loaded (no search) | Human / admin |
| 2 | Agent Memory | DB table + optional vector | Load at session start per agent | Memory writer |
| 3 | Knowledge Rules | DB table | Always loaded (no search) | Nomination pipeline / human |
| 4 | Semantic Memory | DB table + pgvector | Cosine similarity → reranker | Memory writer |
| 5 | Entity Graph | DB table | SQL filter by subject/predicate | Memory writer |
| 6 | Session Logs | DB table | Load last N sessions per context | Session logger |

**Priority order (conflict resolution):** Tier 1 > Tier 3 > Tier 2 > Tier 4 > Tier 5 > Tier 6

---

## Step 1 — Understand the Project Context

Before generating any files, ask:

1. **What is the project name / namespace prefix?** (used to name DB tables, e.g. `myproject_memory`)
2. **What is the agent architecture?** (single agent, supervisor→executor, multi-agent graph?)
3. **What embedding model?** (VoyageAI `voyage-3`, OpenAI `text-embedding-3-large`, Cohere, local?)
4. **Vector dimension?** (1024 for VoyageAI/Cohere, 1536 for OpenAI ada-002, 3072 for text-embedding-3-large)
5. **Is there a multi-tenant concept?** (company_id / tenant_id on every table, or single-tenant?)
6. **Does session continuity matter?** (Tier 6 — if single-session chatbot, can be omitted)
7. **Is human-in-the-loop review needed?** (Tier 3 nomination pipeline — if no humans review, auto-promote only)

Generate everything **after** these answers are confirmed.

---

## Step 2 — Generate: Database Schema

Replace `{PREFIX}` with your project namespace, `{DIM}` with vector dimension.

```sql
-- ============================================================
-- {PREFIX} Persistent Memory Stack — DDL
-- ============================================================

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- Tier 1: Pinned Directives
-- Always loaded at session start. No similarity search.
-- Scopes: global | agent | client (adapt to your domain)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_pinned_documents (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  scope         text        NOT NULL DEFAULT 'global',   -- 'global' | 'agent' | 'client'
  reference_id  uuid,                                    -- agent_id or client_id if scoped
  name          text        NOT NULL,
  content       text        NOT NULL,
  document_type text        NOT NULL DEFAULT 'directive',
  version       text        NOT NULL DEFAULT '1.0',
  is_active     boolean     NOT NULL DEFAULT true,
  metadata      jsonb       NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_pinned_scope_idx
  ON {PREFIX}_pinned_documents (scope, is_active);

-- ------------------------------------------------------------
-- Tier 2: Agent Memory
-- Per-agent persistent knowledge (patterns, heuristics).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_agent_memory (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id         text        NOT NULL,
  content          text        NOT NULL,
  category         text        NOT NULL DEFAULT 'pattern',  -- pattern | preference | heuristic
  topics           text[]      NOT NULL DEFAULT '{}',
  is_active        boolean     NOT NULL DEFAULT true,
  source_session_id text,
  superseded_by_id uuid        REFERENCES {PREFIX}_agent_memory(id) ON DELETE SET NULL,
  metadata         jsonb       NOT NULL DEFAULT '{}',
  embedding        vector({DIM}),
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_agent_memory_agent_idx
  ON {PREFIX}_agent_memory (agent_id, is_active);
CREATE INDEX IF NOT EXISTS {PREFIX}_agent_memory_topics_idx
  ON {PREFIX}_agent_memory USING GIN (topics);

-- ------------------------------------------------------------
-- Tier 3: Knowledge Rules
-- Mandatory constraints. Always loaded. Nomination pipeline feeds here.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_knowledge_rules (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  rule         text        NOT NULL,
  scope        text        NOT NULL DEFAULT 'global',  -- global | agent | client
  reference_id uuid,
  category     text        NOT NULL DEFAULT 'pattern',
  source_type  text        NOT NULL DEFAULT 'agent_inference',  -- agent_inference | human_override
  source_detail text,
  validated_by text,
  is_active    boolean     NOT NULL DEFAULT true,
  metadata     jsonb       NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_rules_scope_idx
  ON {PREFIX}_knowledge_rules (scope, is_active);

-- ------------------------------------------------------------
-- Tier 3 Pipeline: Knowledge Nominations
-- Agents nominate candidate rules → reviewed → promoted to knowledge_rules
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_knowledge_nominations (
  id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  content            text        NOT NULL,
  proposed_scope     text        NOT NULL DEFAULT 'global',
  proposed_category  text        NOT NULL DEFAULT 'pattern',
  nominated_by       text        NOT NULL DEFAULT 'agent',
  source_session_id  text,
  evidence           text,
  status             text        NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | deferred
  reviewed_by        text,
  reviewed_at        timestamptz,
  review_notes       text,
  metadata           jsonb       NOT NULL DEFAULT '{}',
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_nominations_status_idx
  ON {PREFIX}_knowledge_nominations (status, created_at);

-- ------------------------------------------------------------
-- Tier 4: Semantic Memory
-- Long-term knowledge with pgvector similarity search + optional BM25.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_memory (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  content          text        NOT NULL,
  type             text        NOT NULL DEFAULT 'chunk',   -- chunk | summary | fact | reflection
  topics           text[]      NOT NULL DEFAULT '{}',
  client_id        uuid,                                   -- optional: scope to a client/tenant
  agent_id         text,
  source_session_id text,
  parent_chunk_id  uuid        REFERENCES {PREFIX}_memory(id) ON DELETE SET NULL,
  superseded_by_id uuid        REFERENCES {PREFIX}_memory(id) ON DELETE SET NULL,
  embedding_model  text        NOT NULL DEFAULT 'voyage-3',
  embedding        vector({DIM}),
  content_tsv      tsvector    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  metadata         jsonb       NOT NULL DEFAULT '{}',
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_memory_topics_idx
  ON {PREFIX}_memory USING GIN (topics);
CREATE INDEX IF NOT EXISTS {PREFIX}_memory_tsv_idx
  ON {PREFIX}_memory USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS {PREFIX}_memory_client_idx
  ON {PREFIX}_memory (client_id, created_at);

-- HNSW index for ANN vector search (better than IVFFlat for <1M rows)
CREATE INDEX IF NOT EXISTS {PREFIX}_memory_hnsw_idx
  ON {PREFIX}_memory USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- ------------------------------------------------------------
-- Tier 5: Entity Graph
-- Structured facts as subject-predicate-object triples.
-- Temporal: valid_until = NULL means currently active.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_entity_graph (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_type text        NOT NULL,  -- e.g. 'client', 'campaign', 'agent'
  subject_id   text        NOT NULL,  -- UUID or slug
  predicate    text        NOT NULL,  -- e.g. 'prefers_tone', 'budget_cap', 'blocked_by'
  object_value jsonb,                 -- structured value
  object_type  text,                  -- 'text' | 'number' | 'boolean' | 'json'
  object_id    text,                  -- if relation points to another entity
  confidence   real        NOT NULL DEFAULT 1.0,  -- 1.0 = explicit, <1.0 = inferred
  source       text        NOT NULL DEFAULT 'agent',
  valid_from   timestamptz NOT NULL DEFAULT now(),
  valid_until  timestamptz,           -- NULL = currently active
  metadata     jsonb       NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_entity_subject_idx
  ON {PREFIX}_entity_graph (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS {PREFIX}_entity_predicate_idx
  ON {PREFIX}_entity_graph (predicate, valid_until);
CREATE INDEX IF NOT EXISTS {PREFIX}_entity_active_idx
  ON {PREFIX}_entity_graph (subject_id) WHERE valid_until IS NULL;

-- ------------------------------------------------------------
-- Tier 6: Session Logs
-- Continuity context: what happened in recent sessions.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {PREFIX}_session_logs (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id            text        NOT NULL UNIQUE,
  client_record_id      uuid,                     -- optional: scope to a client
  supervisors_involved  text[]      DEFAULT '{}',
  summary               text        NOT NULL,
  task_description      text,
  outcome               text        NOT NULL DEFAULT 'completed',  -- completed | rejected | interrupted
  memory_signals_count  integer     NOT NULL DEFAULT 0,
  duration_ms           integer,
  metadata              jsonb       NOT NULL DEFAULT '{}',
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {PREFIX}_session_client_idx
  ON {PREFIX}_session_logs (client_record_id, created_at DESC);
CREATE INDEX IF NOT EXISTS {PREFIX}_session_created_idx
  ON {PREFIX}_session_logs (created_at DESC);
```

---

## Step 3 — Generate: Retrieval Pipeline

File: `src/pipelines/retrieval.py`

```python
"""
Persistent Memory Stack — Retrieval Pipeline
6-Tier Architecture

Tier 1: Pinned directives — always loaded
Tier 2: Agent memory — per-agent persistent knowledge
Tier 3: Knowledge rules — validated mandatory constraints
Tier 4: Semantic memory — similarity search via pgvector
Tier 5: Entity graph — structured relations
Tier 6: Session logs — recent history for continuity
"""
import logging
from typing import Optional

# Adapt these imports to your project's DB utilities
# See "Adaptation Notes" for SQLAlchemy / other ORM alternatives
from .db import select, execute
from .embeddings_client import get_embeddings, rerank  # rerank is optional

logger = logging.getLogger(__name__)

# Replace with your project prefix (must match DDL above)
_PREFIX = "{PREFIX}"


# ============================================================
# Tier 1 — Pinned Directives
# ============================================================

async def load_tier1(agent_id: Optional[str] = None, client_id: Optional[str] = None) -> list[dict]:
    """Load pinned documents — always in context, no similarity search.
    Fetches global + agent-specific + client-specific documents.
    """
    try:
        params: list = []
        where_parts = ["is_active = TRUE AND scope = 'global'"]

        if agent_id:
            where_parts.append("(scope = 'agent' AND reference_id = %s)")
            params.append(agent_id)
        if client_id:
            where_parts.append("(scope = 'client' AND reference_id = %s)")
            params.append(client_id)

        where_sql = " OR ".join(f"({p})" for p in where_parts)
        docs = await execute(
            f"SELECT * FROM {_PREFIX}_pinned_documents WHERE {where_sql}",
            params,
        )

        logger.info("[retrieval] tier1: loaded %d pinned documents", len(docs))
        return docs
    except Exception as e:
        logger.error("[retrieval] tier1 load failed: %s", e)
        return []


# ============================================================
# Tier 2 — Agent Memory
# ============================================================

async def load_tier2(agent_id: Optional[str] = None) -> list[dict]:
    """Load per-agent persistent knowledge (patterns, preferences, heuristics)."""
    if not agent_id:
        return []
    try:
        memories = await select(
            f"{_PREFIX}_agent_memory",
            filters={"agent_id": agent_id, "is_active": True},
            order="created_at DESC",
        )
        logger.info("[retrieval] tier2: loaded %d agent memories for '%s'", len(memories), agent_id)
        return memories
    except Exception as e:
        logger.error("[retrieval] tier2 load failed for '%s': %s", agent_id, e)
        return []


# ============================================================
# Tier 3 — Knowledge Rules
# ============================================================

async def load_tier3(agent_id: Optional[str] = None, client_id: Optional[str] = None) -> list[dict]:
    """Load validated knowledge rules — mandatory constraints. Always loaded alongside Tier 1."""
    try:
        params: list = []
        where_parts = ["scope = 'global'"]

        if agent_id:
            where_parts.append("(scope = 'agent' AND reference_id = %s)")
            params.append(agent_id)
        if client_id:
            where_parts.append("(scope = 'client' AND reference_id = %s)")
            params.append(client_id)

        scope_sql = " OR ".join(f"({p})" for p in where_parts)
        rules = await execute(
            f"SELECT * FROM {_PREFIX}_knowledge_rules WHERE is_active = TRUE AND ({scope_sql})",
            params,
        )

        logger.info("[retrieval] tier3: loaded %d knowledge rules", len(rules))
        return rules
    except Exception as e:
        logger.error("[retrieval] tier3 load failed: %s", e)
        return []


# ============================================================
# Tier 4 — Semantic Memory (pgvector)
# ============================================================

async def search_tier4(
    query: str,
    client_id: Optional[str] = None,
    topics_filter: Optional[list[str]] = None,
    top_k: int = 5,
) -> list[dict]:
    """Two-stage retrieval:
    1. Cosine similarity via pgvector → broad candidate set (top_k * 4)
    2. Reranker → precise top_k by cross-attention relevance
    Falls back to cosine-only if reranker is unavailable.
    """
    try:
        embedder = get_embeddings()
        if not embedder:
            return []
        vector = await embedder.aembed_query(query)

        candidate_k = top_k * 4
        sql = f"""
            SELECT id, content, type, topics, metadata, client_id,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM {_PREFIX}_memory
            WHERE TRUE
        """
        params: list = [str(vector)]

        if client_id:
            sql += " AND client_id = %s"
            params.append(client_id)
        if topics_filter:
            sql += " AND topics && %s"
            params.append(topics_filter)

        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([str(vector), candidate_k])

        candidates = await execute(sql, params)
        if not candidates:
            return []

        # Stage 2: rerank (optional — falls back gracefully)
        try:
            doc_texts = [c["content"] for c in candidates]
            reranked = await rerank(query=query, documents=doc_texts, top_n=top_k)
            results = []
            for r in reranked:
                idx = r.get("index", 0)
                if idx < len(candidates):
                    entry = dict(candidates[idx])
                    entry["rerank_score"] = r.get("relevance_score", 0.0)
                    results.append(entry)
            logger.info("[retrieval] tier4: %d → reranked to %d", len(candidates), len(results))
            return results
        except Exception:
            results = candidates[:top_k]
            logger.info("[retrieval] tier4: %d results (cosine-only fallback)", len(results))
            return results

    except Exception as e:
        logger.error("[retrieval] tier4 search failed: %s", e)
        return []


# ============================================================
# Tier 5 — Entity Graph
# ============================================================

async def load_tier5(
    subject_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> list[dict]:
    """Load active entity graph relations. No similarity search.

    Args:
        subject_id: Filter by subject (e.g. client UUID)
        subject_type: Filter by entity type (e.g. 'client', 'campaign')
        min_confidence: Minimum confidence threshold.
            None = all facts. 1.0 = explicit only. 0.8 = high confidence.
    """
    if not subject_id and not subject_type:
        return []
    try:
        filters: dict = {"valid_until__is_null": True}
        if subject_id:
            filters["subject_id"] = subject_id
        if subject_type:
            filters["subject_type"] = subject_type

        facts = await select(f"{_PREFIX}_entity_graph", filters=filters, order="created_at DESC")

        if min_confidence is not None:
            facts = [f for f in facts if f.get("confidence") is None or f["confidence"] >= min_confidence]

        logger.info("[retrieval] tier5: loaded %d entity relations", len(facts))
        return facts
    except Exception as e:
        logger.error("[retrieval] tier5 load failed: %s", e)
        return []


# ============================================================
# Tier 6 — Session Logs
# ============================================================

async def load_tier6(client_id: Optional[str] = None, limit: int = 5) -> list[dict]:
    """Load recent session logs — continuity context."""
    if not client_id:
        return []
    try:
        sessions = await select(
            f"{_PREFIX}_session_logs",
            columns="session_id, supervisors_involved, summary, outcome, created_at",
            filters={"client_record_id": client_id},
            order="created_at DESC",
            limit=limit,
        )
        logger.info("[retrieval] tier6: loaded %d recent sessions", len(sessions))
        return sessions
    except Exception as e:
        logger.error("[retrieval] tier6 load failed: %s", e)
        return []
```

---

## Step 4 — Generate: Memory Writer

File: `src/pipelines/memory_writer.py`

```python
"""
Persistent Memory Stack — Memory Writer
Routes agent signals to the correct tier.

Only ONE component should write to memory (the orchestrator/supervisor).
Sub-agents signal via a shared state field (e.g. `memory_signals`).

Signal schema:
{
    "content": str,                    # Required — the text to persist
    "type": str,                       # Optional — chunk | summary | fact | reflection
    "topics": list[str],               # Optional — for filtering
    "client_id": str,                  # Optional — scope to a tenant/client
    "metadata": dict,                  # Optional — arbitrary metadata
    "agent_memory_target": str,        # → Tier 2 (agent_id to write to)
    "nominate_as_rule": bool,          # → Tier 3 nomination pipeline
    "entity_facts": list[dict],        # → Tier 5 (list of subject/predicate/object dicts)
}
"""
import logging
from typing import Any, Optional

from .db import insert, select
from .embeddings_client import get_embeddings

logger = logging.getLogger(__name__)

_PREFIX = "{PREFIX}"


async def evaluate_and_write(state: dict) -> dict:
    """Entry point. Pass the full agent state dict."""
    return await _classify_and_write(state)


async def _classify_and_write(state: dict) -> dict:
    signals = state.get("memory_signals", [])
    if not signals:
        return {"memory_written": False}

    embedder = get_embeddings()
    counts = {"tier2": 0, "tier3": 0, "tier4": 0, "tier5": 0}
    session_id = state.get("session_id") or state.get("task_id")

    try:
        for signal in signals:
            content = signal.get("content")
            if not content:
                continue

            if agent_target := signal.get("agent_memory_target"):
                await _write_tier2(signal, agent_target, session_id)
                counts["tier2"] += 1

            if signal.get("nominate_as_rule"):
                await _write_tier3_nomination(signal, session_id)
                counts["tier3"] += 1

            for fact in signal.get("entity_facts", []):
                if await _write_tier5(fact):
                    counts["tier5"] += 1

            if embedder:
                await _write_tier4(embedder, signal, session_id)
                counts["tier4"] += 1

        logger.info(
            "[memory_writer] T2=%d T3=%d T4=%d T5=%d",
            counts["tier2"], counts["tier3"], counts["tier4"], counts["tier5"],
        )
        return {"memory_written": True, "write_counts": counts}

    except Exception as e:
        logger.error("[memory_writer] Failed: %s", e)
        return {"memory_written": False, "error": str(e)}


async def _write_tier2(signal: dict, agent_id: str, session_id: Optional[str]) -> None:
    await insert(f"{_PREFIX}_agent_memory", {
        "agent_id": agent_id,
        "content": signal["content"],
        "category": signal.get("metadata", {}).get("category", "pattern"),
        "topics": signal.get("topics", []),
        "source_session_id": session_id,
    })


async def _write_tier3_nomination(signal: dict, session_id: Optional[str]) -> None:
    meta = signal.get("metadata", {})
    await insert(f"{_PREFIX}_knowledge_nominations", {
        "content": signal["content"],
        "proposed_scope": meta.get("proposed_scope", "global"),
        "proposed_category": meta.get("proposed_category", "pattern"),
        "nominated_by": meta.get("nominated_by", "agent"),
        "source_session_id": session_id,
        "evidence": meta.get("evidence", ""),
    })


async def _write_tier4(embedder: Any, signal: dict, session_id: Optional[str]) -> None:
    embedding_vector = embedder.embed_query(signal["content"])
    row: dict[str, Any] = {
        "content": signal["content"],
        "type": signal.get("type", "chunk"),
        "topics": signal.get("topics", []),
        "embedding": str(embedding_vector),
        "source_session_id": session_id,
        "metadata": signal.get("metadata", {}),
    }
    if signal.get("client_id"):
        row["client_id"] = signal["client_id"]
    await insert(f"{_PREFIX}_memory", row)


async def _write_tier5(fact: dict) -> bool:
    """Write entity fact with Tier 3 conflict check.
    Returns True if written, False if blocked by a conflicting rule.
    """
    conflicting_rule = await _check_tier3_conflict(fact)
    if conflicting_rule:
        logger.warning(
            "[memory_writer] Tier 5 fact blocked by Tier 3 rule: %s:%s → rule %s",
            fact["subject_id"], fact["predicate"], conflicting_rule["id"],
        )
        return False

    row: dict[str, Any] = {
        "subject_type": fact["subject_type"],
        "subject_id": fact["subject_id"],
        "predicate": fact["predicate"],
        "source": fact.get("source", "agent"),
    }
    for key in ("object_type", "object_id", "object_value", "confidence"):
        if fact.get(key) is not None:
            row[key] = fact[key]

    await insert(f"{_PREFIX}_entity_graph", row)
    return True


async def _check_tier3_conflict(fact: dict) -> Optional[dict]:
    """Check if a Tier 5 fact conflicts with an active Tier 3 rule.
    Conflict pattern: rule content contains "NOT|FORBID|CANNOT <subject_type>:<predicate>"
    """
    try:
        fact_key = f"{fact['subject_type']}:{fact['predicate']}".upper()
        rules = await select(f"{_PREFIX}_knowledge_rules", filters={"is_active": True})
        for rule in rules:
            content = rule.get("rule", rule.get("content", "")).upper()
            if any(f"{kw} {fact_key}" in content for kw in ("NOT", "FORBID", "CANNOT")):
                return rule
        return None
    except Exception as e:
        logger.error("[memory_writer] Tier 3 conflict check failed: %s", e)
        return None
```

---

## Step 5 — Generate: Entity Extractor Utilities

File: `src/pipelines/entity_extractor.py`

```python
"""
Entity Extractor — Tier 5 utilities
Upsert facts with temporal auditability (invalidate old → insert new).
"""
import logging
from typing import Optional

from .db import select, insert, update

logger = logging.getLogger(__name__)
_PREFIX = "{PREFIX}"


async def upsert_entity_fact(
    subject_type: str,
    subject_id: str,
    predicate: str,
    object_value: Optional[dict] = None,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    confidence: float = 1.0,
    source: str = "agent",
) -> bool:
    """Invalidate existing active fact for (subject_type, subject_id, predicate),
    then insert the new one. Preserves temporal auditability.
    """
    try:
        await update(
            f"{_PREFIX}_entity_graph",
            values={"valid_until": "now()"},
            filters={
                "subject_type": subject_type,
                "subject_id": subject_id,
                "predicate": predicate,
                "valid_until__is_null": True,
            },
        )
        row: dict = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "predicate": predicate,
            "confidence": confidence,
            "source": source,
        }
        for key, val in [("object_value", object_value), ("object_type", object_type), ("object_id", object_id)]:
            if val is not None:
                row[key] = val
        await insert(f"{_PREFIX}_entity_graph", row)
        return True
    except Exception as e:
        logger.error("[entity_extractor] upsert failed: %s", e)
        return False


async def query_by_predicate(predicate: str, subject_type: Optional[str] = None) -> list[dict]:
    """Query active entity facts by predicate."""
    try:
        filters: dict = {"predicate": predicate, "valid_until__is_null": True}
        if subject_type:
            filters["subject_type"] = subject_type
        return await select(f"{_PREFIX}_entity_graph", filters=filters)
    except Exception as e:
        logger.error("[entity_extractor] query_by_predicate failed: %s", e)
        return []
```

---

## Step 6 — Generate: Nomination Manager

File: `src/pipelines/nomination_manager.py`

```python
"""
Nomination Manager — Tier 3 lifecycle
pending → approved (promoted to knowledge_rules) | rejected | deferred

Promotion paths:
  1. Auto-threshold: N independent nominations → auto-promote
  2. Human review: approve/reject via admin interface
"""
import logging
from typing import Optional

from .db import select, insert, update, count

logger = logging.getLogger(__name__)
_PREFIX = "{PREFIX}"
AUTO_PROMOTE_THRESHOLD = 3  # tune per project


async def check_and_auto_promote(content: str) -> bool:
    """Auto-promote if content has been independently nominated >= AUTO_PROMOTE_THRESHOLD times."""
    try:
        n = await count(f"{_PREFIX}_knowledge_nominations", filters={"status": "pending", "content": content})
        if n >= AUTO_PROMOTE_THRESHOLD:
            return await promote_nomination(content, validated_by="auto_threshold")
        return False
    except Exception as e:
        logger.error("[nomination_manager] check_and_auto_promote failed: %s", e)
        return False


async def promote_nomination(
    content: str,
    scope: str = "global",
    category: str = "pattern",
    reference_id: Optional[str] = None,
    validated_by: str = "auto_threshold",
) -> bool:
    """Promote nomination to knowledge_rule and mark all matching nominations as approved."""
    try:
        rule_row: dict = {
            "rule": content,
            "scope": scope,
            "category": category,
            "source_type": "agent_inference",
            "source_detail": "auto-promoted from nominations",
            "validated_by": validated_by,
        }
        if reference_id:
            rule_row["reference_id"] = reference_id
        await insert(f"{_PREFIX}_knowledge_rules", rule_row)
        await update(
            f"{_PREFIX}_knowledge_nominations",
            values={"status": "approved", "reviewed_by": validated_by},
            filters={"content": content, "status": "pending"},
        )
        logger.info("[nomination_manager] Promoted: %s...", content[:80])
        return True
    except Exception as e:
        logger.error("[nomination_manager] promote failed: %s", e)
        return False


async def get_pending_nominations(limit: int = 20) -> list[dict]:
    try:
        return await select(
            f"{_PREFIX}_knowledge_nominations",
            filters={"status": "pending"},
            order="created_at ASC",
            limit=limit,
        )
    except Exception as e:
        logger.error("[nomination_manager] get_pending failed: %s", e)
        return []
```

---

## Step 7 — Generate: Session Logger

File: `src/pipelines/session_logger.py`

```python
"""
Session Logger — Tier 6 persistence
Non-critical: errors are logged but never fail the main pipeline.
"""
import logging
from typing import Any, Optional

from .db import insert

logger = logging.getLogger(__name__)
_PREFIX = "{PREFIX}"


async def log_session(state: dict) -> dict:
    """Write session summary to Tier 6.
    Call at the end of every agent session.
    """
    session_id = state.get("session_id") or state.get("task_id")
    if not session_id:
        return {}

    task = state.get("task", "")
    client_id = state.get("client_id")
    rejection_code = state.get("rejection_code")
    signals = state.get("memory_signals", [])

    if rejection_code:
        outcome = "rejected"
    elif state.get("requires_interrupt"):
        outcome = "interrupted"
    else:
        outcome = "completed"

    row: dict[str, Any] = {
        "session_id": session_id,
        "summary": task[:500] if task else "(empty)",
        "task_description": task[:1000] if task else None,
        "outcome": outcome,
        "memory_signals_count": len(signals),
        "metadata": {
            "outcome_detail": (state.get("final_response") or "")[:500],
        },
    }
    if supervisor := (state.get("instruction_packet") or {}).get("supervisor"):
        row["supervisors_involved"] = [supervisor]
    if client_id:
        row["client_record_id"] = client_id

    try:
        await insert(f"{_PREFIX}_session_logs", row)
        logger.info("[session_logger] Logged session %s (%s)", session_id, outcome)
    except Exception as e:
        logger.error("[session_logger] Failed to log session %s: %s", session_id, e)

    return {}
```

---

## Step 8 — Wire into Your Agent Graph

In your orchestrator (LangGraph node or equivalent):

```python
from src.pipelines.retrieval import load_tier1, load_tier2, load_tier3, search_tier4, load_tier5, load_tier6
from src.pipelines.memory_writer import evaluate_and_write
from src.pipelines.session_logger import log_session

# At session START — load context
async def build_context(agent_id: str, client_id: str, query: str) -> dict:
    tier1 = await load_tier1(agent_id=agent_id, client_id=client_id)
    tier2 = await load_tier2(agent_id=agent_id)
    tier3 = await load_tier3(agent_id=agent_id, client_id=client_id)
    tier4 = await search_tier4(query=query, client_id=client_id)
    tier5 = await load_tier5(subject_id=client_id, subject_type="client")
    tier6 = await load_tier6(client_id=client_id)
    return {
        "directives": tier1,
        "agent_memory": tier2,
        "knowledge_rules": tier3,
        "semantic_results": tier4,
        "entity_facts": tier5,
        "recent_sessions": tier6,
    }

# At session END — persist memory and log
async def finalize_session(state: dict) -> None:
    await evaluate_and_write(state)  # writes tier2/3/4/5
    await log_session(state)         # writes tier6
```

**Expected `state` fields for the writer:**
```python
state = {
    "session_id": "uuid-or-string",
    "task": "user query or task description",
    "client_id": "uuid",                   # optional
    "rejection_code": None,                # or "rejected:reason"
    "requires_interrupt": False,           # True if HITL needed
    "final_response": "...",               # agent's final output
    "memory_signals": [                    # list of signals from sub-agents
        {
            "content": "Client prefers formal tone",
            "type": "fact",
            "topics": ["tone", "preferences"],
            "client_id": "uuid",
            "nominate_as_rule": False,
            "entity_facts": [
                {
                    "subject_type": "client",
                    "subject_id": "uuid",
                    "predicate": "prefers_tone",
                    "object_value": {"value": "formal"},
                    "confidence": 1.0,
                }
            ],
        }
    ],
}
```

---

## Adaptation Notes

### SQLAlchemy (sync or async)

Replace `execute()` / `select()` / `insert()` calls with SQLAlchemy Core or ORM equivalents.
The vector column becomes `Column(Vector(dim))` with `pgvector-sqlalchemy`.
The pgvector cosine operator `<=>` is available via `l2_distance` / `cosine_distance` from `pgvector.sqlalchemy`.

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Text
# embedding = Column(Vector(1024))
# query: session.query(Memory).order_by(Memory.embedding.cosine_distance(query_vec)).limit(20)
```

### MongoDB (Tier 4 only)

MongoDB Atlas Vector Search can replace Tier 4 pgvector.
Tiers 1/2/3/5/6 remain as separate collections.
Use `$vectorSearch` aggregation pipeline instead of the `<=>` operator.
Note: you lose the hybrid BM25+vector retrieval on `content_tsv`.

### Qdrant / Weaviate / Pinecone (Tier 4 only)

Replace Tier 4 table + HNSW index with a dedicated vector DB collection.
Store only `id`, `content`, `metadata` in the vector DB; keep Tiers 1/2/3/5/6 in PostgreSQL.
Use the vector DB's native reranker integration if available.

### Sync Python (no async)

Remove `await` and `async def`. Replace `asyncpg`/`psycopg3` pool with `psycopg2` or `psycopg3` sync.
`embedder.aembed_query()` → `embedder.embed_query()`.

### Single-tenant (no company_id / client_id)

Remove all `client_id` / `company_id` columns from DDL and filter clauses.
Drop Tier 6 `client_record_id` filter — load last N sessions globally instead.

### No reranker

The reranker is optional. `search_tier4` already falls back to cosine-only if `rerank()` raises.
Simply remove the `rerank` import and the Stage 2 block — the function works correctly with cosine-only.

### No Tier 6 (single-session or stateless)

Omit `{PREFIX}_session_logs` table and `session_logger.py`. 
Call `evaluate_and_write()` only (skips session logging entirely).

---

## Checklist Before First Run

- [ ] `{PREFIX}` replaced everywhere (DDL, Python files, config)
- [ ] `{DIM}` set to correct vector dimension for your embedding model
- [ ] `pgvector` extension installed on PostgreSQL
- [ ] Embedding model credentials configured
- [ ] `AUTO_PROMOTE_THRESHOLD` tuned (default: 3)
- [ ] DB pool / connection helper wired into `db.py`
- [ ] `memory_signals` field added to your agent state schema
- [ ] `finalize_session()` called at the end of every agent run

---

## When to Use This Skill

- Starting a new AI agent project that needs cross-session memory
- Adding persistent memory to an existing agent that currently has none
- Evaluating whether this architecture fits your project (read the tier table + adaptation notes first)
