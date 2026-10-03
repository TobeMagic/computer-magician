"""Writer-lens sentences used by series minting.

These are internal writing instructions. They must never appear in
topic_summary, opening_hook, or reader-visible body.
"""

from __future__ import annotations

import re

WRITER_LENS_BY_KIND = {
    "industry_insight": "从行业局势、商业影响与从业者判断来写。",
    "solution_architecture": "从可落地的方案、选型取舍与实施路径来写。",
    "architecture_design": "从机制、系统架构与工程边界来写。",
}
WRITER_LENS_SENTENCES = tuple(WRITER_LENS_BY_KIND.values())


def is_writer_lens_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return False
    for sentence in WRITER_LENS_SENTENCES:
        needle = re.sub(r"\s+", "", sentence)
        if compact == needle or compact.startswith(needle):
            return True
    return False


def strip_writer_lens(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for sentence in WRITER_LENS_SENTENCES:
        if value.startswith(sentence):
            value = value[len(sentence) :].lstrip()
        value = value.replace(sentence, "").strip()
    return value
