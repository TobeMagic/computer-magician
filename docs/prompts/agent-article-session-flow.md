# Agent Article Session Flow Prompt Source

Purpose: provide the canonical article session flow for MCP agents.

## New Article Flow

1. Convert a hot topic, user seed, URL, or series entry into an AImagician topic/article flow.
2. Confirm style, target word count, publish scope, and any request-level prompt guidance.
3. Generate title options, summary, outline, golden quote lines, and opening hook.
4. Ask the user to confirm or modify the preview fields.
5. Run research and persist evidence/source notes/research report.
6. Generate body from confirmed preview plus evidence.
7. Run quality and formatting gates.
8. Store the current article version in Postgres and lazy-sync external mirrors.
9. Generate three cover visual briefs, ask for confirmation, render three candidates, and commit the selected cover.
10. Publish by selected scope and update publication matrix.

## Existing Article Flow

1. Search articles by title/topic keywords.
2. Show status, current version, and publication matrix.
3. If body inspection is needed, read versions and body through MCP.
4. If editing is needed, create a new version through MCP.
5. Publish missing platforms only.

