"""Tier 1 — Static Knowledge Base loader.

Parses agent knowledge bases (`Riferimenti/agents/*.md`) into structured
blocks that can be looked up by id, tag, agent, or type prefix.

Block format expected in markdown:

    ### `BLOCK-ID-001` — Optional Title
    **Tags**: `tag1, tag2`

    ```yaml
    body: ...
    ```

The block id prefix (`HARD`, `PARAM`, `HEUR`, `PROMPT`, `REF`) classifies
the block type. The owning agent is taken from the file's YAML frontmatter
(`agent:` field) so the same loader works for any agent file.

Files are read at construction time. The loader is read-only and cheap to
keep in memory; reload by instantiating again.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# `### \`HARD-MIND-001\` — Title`  (the dash + title is optional)
_HEADING_RE = re.compile(r"^###\s+`([A-Z][A-Z0-9_-]*)`(?:\s*[—\-]\s*(.+))?\s*$")
# `**Tags**: \`tag1, tag2\``
_TAGS_RE = re.compile(r"^\*\*Tags\*\*\s*:\s*`([^`]+)`\s*$")
# Fenced code block opener: ``` or ```yaml etc.
_FENCE_RE = re.compile(r"^```(\w*)\s*$")
# Frontmatter `agent: name`
_FRONTMATTER_AGENT_RE = re.compile(r"^agent:\s*(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class KBBlock:
    """A single knowledge base block parsed from a markdown KB file."""

    id: str
    type: str  # HARD | PARAM | HEUR | PROMPT | REF | OTHER
    title: str
    tags: tuple[str, ...]
    body: str
    body_format: str  # yaml | json | python | text | ""
    agent: str
    source_file: str

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def has_any_tag(self, tags: Iterable[str]) -> bool:
        wanted = set(tags)
        return any(t in wanted for t in self.tags)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Both are '' if no frontmatter."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    fm = text[4:end]
    rest_start = end + len("\n---")
    # Skip the trailing newline after closing ---
    if rest_start < len(text) and text[rest_start] in "\r\n":
        rest_start += 1
        if rest_start < len(text) and text[rest_start] == "\n":
            rest_start += 1
    return fm, text[rest_start:]


def _classify_id(block_id: str) -> str:
    prefix = block_id.split("-", 1)[0]
    if prefix in {"HARD", "PARAM", "HEUR", "PROMPT", "REF"}:
        return prefix
    return "OTHER"


def _parse_file(path: Path) -> list[KBBlock]:
    """Parse one markdown KB file into a list of blocks."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)

    agent_match = _FRONTMATTER_AGENT_RE.search(frontmatter) if frontmatter else None
    agent = agent_match.group(1) if agent_match else path.stem

    blocks: list[KBBlock] = []
    lines = body.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        m = _HEADING_RE.match(line)
        if not m:
            i += 1
            continue

        block_id = m.group(1)
        title = (m.group(2) or "").strip()
        i += 1

        # Optional blank lines, then optional tags line
        tags: tuple[str, ...] = ()
        while i < n and lines[i].strip() == "":
            i += 1
        if i < n:
            tags_match = _TAGS_RE.match(lines[i])
            if tags_match:
                tags = tuple(t.strip() for t in tags_match.group(1).split(",") if t.strip())
                i += 1

        # Optional blank lines, then optional fenced body
        while i < n and lines[i].strip() == "":
            i += 1

        body_format = ""
        body_lines: list[str] = []
        if i < n:
            fence = _FENCE_RE.match(lines[i])
            if fence:
                body_format = fence.group(1) or ""
                i += 1
                while i < n and not lines[i].startswith("```"):
                    body_lines.append(lines[i])
                    i += 1
                if i < n:
                    i += 1  # consume closing fence

        blocks.append(
            KBBlock(
                id=block_id,
                type=_classify_id(block_id),
                title=title,
                tags=tags,
                body="\n".join(body_lines),
                body_format=body_format,
                agent=agent,
                source_file=str(path),
            )
        )

    return blocks


@dataclass
class KBLoader:
    """Read-only registry of knowledge base blocks parsed from .md files.

    Usage:
        loader = KBLoader.from_directory(Path("Riferimenti/agents"))
        block = loader.get("HARD-ANALYST-002")
        analyst_hard_rules = loader.find(agent="analyst", type="HARD")
    """

    blocks: list[KBBlock] = field(default_factory=list)
    _by_id: dict[str, KBBlock] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {b.id: b for b in self.blocks}

    @classmethod
    def from_directory(cls, directory: Path | str) -> "KBLoader":
        """Parse every `*.md` file in the directory (non-recursive, skips INDEX.md)."""
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"KB directory not found: {directory}")

        all_blocks: list[KBBlock] = []
        for path in sorted(directory.glob("*.md")):
            if path.name.upper() == "INDEX.MD":
                continue
            try:
                all_blocks.extend(_parse_file(path))
            except Exception:
                logger.exception("[kb_loader] failed to parse %s", path)
        logger.info(
            "[kb_loader] loaded %d blocks from %s", len(all_blocks), directory
        )
        return cls(blocks=all_blocks)

    @classmethod
    def from_files(cls, paths: Iterable[Path | str]) -> "KBLoader":
        """Parse a specific list of files."""
        all_blocks: list[KBBlock] = []
        for raw in paths:
            path = Path(raw)
            try:
                all_blocks.extend(_parse_file(path))
            except Exception:
                logger.exception("[kb_loader] failed to parse %s", path)
        return cls(blocks=all_blocks)

    # ---- lookups -----------------------------------------------------------

    def get(self, block_id: str) -> KBBlock | None:
        return self._by_id.get(block_id)

    def find(
        self,
        *,
        agent: str | None = None,
        type: str | None = None,  # noqa: A002 — matches block.type
        tag: str | None = None,
        any_tag: Iterable[str] | None = None,
    ) -> list[KBBlock]:
        """Filter blocks. All conditions are AND-combined; omit to skip."""
        wanted_any = set(any_tag) if any_tag else None
        result = []
        for b in self.blocks:
            if agent is not None and b.agent != agent:
                continue
            if type is not None and b.type != type:
                continue
            if tag is not None and tag not in b.tags:
                continue
            if wanted_any is not None and not any(t in wanted_any for t in b.tags):
                continue
            result.append(b)
        return result

    def for_agent(self, agent: str) -> list[KBBlock]:
        return self.find(agent=agent)

    def __len__(self) -> int:
        return len(self.blocks)

    def __contains__(self, block_id: object) -> bool:
        return isinstance(block_id, str) and block_id in self._by_id
