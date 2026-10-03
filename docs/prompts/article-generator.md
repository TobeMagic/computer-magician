# Article Generator Prompt Source

Purpose: define the native article generation contract.

## Inputs

- Confirmed title.
- Confirmed summary.
- Confirmed outline.
- Confirmed opening hook.
- Confirmed golden quote lines.
- Target word count and tolerated range.
- Research evidence and source notes.
- Series style append and request style append.

## Output Contract

- Return structured output with `body_markdown`, `quality_notes`, `word_count`, and optional media placeholders.
- Use Markdown headings for body sections only.
- Use `mermaid` blocks only when a diagram helps; produce valid Mermaid source.
- Use reaction placeholders only when a human expression improves rhythm.
- Keep normal code blocks as code blocks; only Mermaid diagram blocks are rendered into images.
