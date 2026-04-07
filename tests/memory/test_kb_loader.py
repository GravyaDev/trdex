"""Unit tests for the Tier 1 KB loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from trdex.memory.kb_loader import KBBlock, KBLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_DIR = REPO_ROOT / "Riferimenti" / "agents"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parses_block_with_tags_and_yaml_body(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "demo.md",
        """---
agent: demo
version: 1.0
---

# Demo KB

### `HARD-DEMO-001` — A Rule
**Tags**: `mindset, prohibited`

```yaml
rule: foo
value: 1
```
""",
    )

    loader = KBLoader.from_directory(tmp_path)
    assert len(loader) == 1

    block = loader.get("HARD-DEMO-001")
    assert block is not None
    assert block.type == "HARD"
    assert block.title == "A Rule"
    assert block.tags == ("mindset", "prohibited")
    assert block.body_format == "yaml"
    assert "rule: foo" in block.body
    assert block.agent == "demo"


def test_classifies_id_prefix_as_other_when_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.md",
        """---
agent: x
---

### `WEIRD-001` — t
**Tags**: `a`

```text
body
```
""",
    )
    loader = KBLoader.from_directory(tmp_path)
    assert loader.get("WEIRD-001").type == "OTHER"


def test_find_filters_by_agent_type_tag(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        """---
agent: alpha
---

### `HARD-A-1`
**Tags**: `mindset`

```yaml
v: 1
```

### `PARAM-A-1`
**Tags**: `indicator, rsi`

```yaml
v: 2
```
""",
    )
    _write(
        tmp_path,
        "b.md",
        """---
agent: beta
---

### `HARD-B-1`
**Tags**: `mindset`

```yaml
v: 3
```
""",
    )
    loader = KBLoader.from_directory(tmp_path)

    assert {b.id for b in loader.find(agent="alpha")} == {"HARD-A-1", "PARAM-A-1"}
    assert {b.id for b in loader.find(type="HARD")} == {"HARD-A-1", "HARD-B-1"}
    assert {b.id for b in loader.find(tag="rsi")} == {"PARAM-A-1"}
    assert {b.id for b in loader.find(agent="alpha", type="HARD")} == {"HARD-A-1"}


def test_skips_index_md(tmp_path: Path) -> None:
    _write(tmp_path, "INDEX.md", "### `HARD-IGN-1`\n```yaml\nv: 0\n```\n")
    _write(
        tmp_path,
        "real.md",
        """---
agent: real
---

### `HARD-REAL-1`

```yaml
v: 1
```
""",
    )
    loader = KBLoader.from_directory(tmp_path)
    assert "HARD-IGN-1" not in loader
    assert "HARD-REAL-1" in loader


def test_block_without_tags_or_body(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "x.md",
        """---
agent: x
---

### `REF-X-1` — title only
""",
    )
    loader = KBLoader.from_directory(tmp_path)
    block = loader.get("REF-X-1")
    assert block is not None
    assert block.tags == ()
    assert block.body == ""
    assert block.body_format == ""
    assert block.title == "title only"


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        KBLoader.from_directory(tmp_path / "nope")


@pytest.mark.skipif(not KB_DIR.exists(), reason="Riferimenti/agents/ not present")
def test_real_kb_directory_loads_known_blocks() -> None:
    loader = KBLoader.from_directory(KB_DIR)
    assert len(loader) > 0
    # Sanity-check a few well-known blocks from analyst.md
    assert "HARD-ANALYST-002" in loader
    analyst_blocks = loader.for_agent("analyst")
    assert any(b.type == "HARD" for b in analyst_blocks)
    assert any(b.type == "PARAM" for b in analyst_blocks)
