# Article Style Checker Prompt Source

Purpose: define quality review and warning feedback for generated articles.

## Review Areas

- Confirmed title, summary, outline, hook, and word count are respected.
- Research evidence is sufficient for factual/technical claims.
- No raw Infographic DSL, reaction placeholders, or malformed SVG leaks into platform output.
- WeChat HTML includes golden quote, table of contents, recent posts, footer, and rendered images.
- Reaction images do not repeat inside one article and usage is auditable.
- References are appropriate to article type.

## Warning Handling

- Blockers prevent publication.
- Warnings are recorded and should improve upstream prompts/runtime behavior.
- Repeated warnings should not become endless repair loops.

