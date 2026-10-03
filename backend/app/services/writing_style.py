"""Shared loader for the article writing style declaration.

Reads docs/prompts/article-style-declaration.md once and exposes a full
version (injected into the article body prompt) and a condensed version
(injected into the title/outline prompt).

The file is split at the marker "## 15. 标题与大纲精简版". Everything before
that marker is the full style declaration; the section itself is the
condensed version used for title/summary/opening hook/outline generation.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STYLE_FILE = WORKSPACE_ROOT / "docs" / "prompts" / "article-style-declaration.md"
CONDENSED_SECTION_MARKER = "## 15. 标题与大纲精简版"
FULL_STYLE_MAX_CHARS = 12000
CONDENSED_STYLE_MAX_CHARS = 3000


def _load_style_file() -> str:
    path = Path(os.environ.get("AIMAGICIAN_STYLE_DECLARATION_FILE", str(DEFAULT_STYLE_FILE)))
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@functools.lru_cache(maxsize=1)
def load_full_style() -> str:
    """Full writing style declaration for the article body prompt."""
    text = _load_style_file()
    if not text:
        return ""
    idx = text.find(CONDENSED_SECTION_MARKER)
    if idx > 0:
        text = text[:idx]
    return text[:FULL_STYLE_MAX_CHARS]


@functools.lru_cache(maxsize=1)
def load_condensed_style() -> str:
    """Condensed style declaration for the title/outline prompt."""
    text = _load_style_file()
    if not text:
        return ""
    idx = text.find(CONDENSED_SECTION_MARKER)
    if idx < 0:
        return ""
    section = text[idx:]
    end = section.find("\n## ")
    if end > 0:
        section = section[:end]
    return section.strip()[:CONDENSED_STYLE_MAX_CHARS]
