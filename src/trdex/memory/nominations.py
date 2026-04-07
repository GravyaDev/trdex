"""Tier 3 — Knowledge Nominations writer.

Agents can call ``nominate()`` to propose a learning. Entries are appended to
``.claude/knowledge-nominations.md`` for the auditor to review during the
next audit cycle.

Each entry is a Markdown block with structured frontmatter:

    ### NOM-2026-04-07-a3b1c9d2
    - **agent**: analyst
    - **kind**: heuristic_revision
    - **summary**: RSI threshold 30 too aggressive on high-vol regimes
    - **evidence**: 12 of last 20 BTC oversold signals on cv>0.04 lost money
    - **proposed_rule**: when cv>0.04, raise RSI buy threshold to 25
    - **created_at**: 2026-04-07T09:30:00Z

    ```yaml
    extra:
      sample_size: 20
      win_rate_below_threshold: 0.4
    ```

Idempotency: the entry id is a content hash of (agent, kind, summary). If the
same nomination already exists in the file, ``nominate()`` returns the
existing id without appending a duplicate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_NOMINATIONS_PATH = Path(".claude/knowledge-nominations.md")
PENDING_HEADER = "## Pending Nominations"

_HEADER_RE = re.compile(r"^### NOM-\d{4}-\d{2}-\d{2}-([0-9a-f]{8})\s*$", re.MULTILINE)


@dataclass
class Nomination:
    """A single learning candidate proposed by an agent."""

    id: str
    agent: str
    kind: str
    summary: str
    evidence: str
    proposed_rule: str
    created_at: datetime
    extra: dict[str, Any] | None = None

    def render(self) -> str:
        """Render the nomination as a Markdown block."""
        ts = self.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = [
            f"### {self.id}",
            f"- **agent**: {self.agent}",
            f"- **kind**: {self.kind}",
            f"- **summary**: {self.summary}",
            f"- **evidence**: {self.evidence}",
            f"- **proposed_rule**: {self.proposed_rule}",
            f"- **created_at**: {ts}",
        ]
        if self.extra:
            block.append("")
            block.append("```yaml")
            block.append("extra:")
            for k, v in self.extra.items():
                block.append(f"  {k}: {json.dumps(v)}")
            block.append("```")
        return "\n".join(block) + "\n"


def _content_hash(agent: str, kind: str, summary: str) -> str:
    digest = hashlib.sha1(
        f"{agent}|{kind}|{summary.strip().lower()}".encode("utf-8")
    ).hexdigest()
    return digest[:8]


def _make_id(agent: str, kind: str, summary: str, *, now: datetime) -> str:
    date = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"NOM-{date}-{_content_hash(agent, kind, summary)}"


def _existing_ids(text: str) -> set[str]:
    """Return the set of full nomination ids already present in the file."""
    ids: set[str] = set()
    for line in text.splitlines():
        if line.startswith("### NOM-"):
            ids.add(line[4:].strip())
    return ids


def _existing_hashes(text: str) -> set[str]:
    """Return the set of 8-char content hashes already present in the file."""
    return set(_HEADER_RE.findall(text))


def nominate(
    agent: str,
    kind: str,
    summary: str,
    *,
    evidence: str = "",
    proposed_rule: str = "",
    extra: dict[str, Any] | None = None,
    path: Path | str = DEFAULT_NOMINATIONS_PATH,
    now: datetime | None = None,
) -> Nomination:
    """Append a new nomination to the nominations file (or skip if duplicate).

    Returns the Nomination dataclass either way. The ``id`` field can be used
    by callers to log "nomination NOM-... raised".
    """
    if not agent or not kind or not summary:
        raise ValueError("agent, kind and summary are required")

    now = now or datetime.now(tz=timezone.utc)
    nom = Nomination(
        id=_make_id(agent, kind, summary, now=now),
        agent=agent,
        kind=kind,
        summary=summary.strip(),
        evidence=evidence.strip(),
        proposed_rule=proposed_rule.strip(),
        created_at=now,
        extra=extra,
    )

    file_path = Path(path)
    existing = ""
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")

    if _content_hash(agent, kind, summary) in _existing_hashes(existing):
        logger.debug("[nominations] duplicate skipped: %s", nom.id)
        return nom

    if not existing:
        existing = (
            "# Knowledge Nominations\n\n"
            "Candidate learnings from agents and sessions. The auditor reviews these\n"
            "during each audit cycle and promotes valid ones to knowledge-base.md.\n\n"
            f"{PENDING_HEADER}\n"
        )
    elif PENDING_HEADER not in existing:
        existing = existing.rstrip() + f"\n\n{PENDING_HEADER}\n"

    block = nom.render()
    new_content = existing.rstrip() + "\n\n" + block
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(new_content, encoding="utf-8")
    logger.info("[nominations] %s by %s — %s", nom.id, agent, summary[:60])
    return nom


def list_pending(path: Path | str = DEFAULT_NOMINATIONS_PATH) -> list[str]:
    """Return ids of nominations currently in the file."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    return sorted(_existing_ids(file_path.read_text(encoding="utf-8")))
