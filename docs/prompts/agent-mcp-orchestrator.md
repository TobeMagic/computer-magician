# Agent MCP Orchestrator Prompt Source

Purpose: define how any external agent should operate AImagician through MCP.

## Hard Rules

- Treat AImagician/Postgres as the runtime source of truth.
- Use MCP tools/resources/prompts only.
- Do not call legacy scripts, bridge CLI, operator router, or external Notion pages as runtime entrypoints.
- If an MCP tool is missing, report an AImagician backend capability gap with the desired user outcome.
- Refresh the agent access token when authentication fails, then retry the same MCP call once.

## Default Control Flow

1. Inspect `aimagician_capabilities`.
2. Resolve article/topic/run state with AImagician search tools.
3. Use explicit confirm tools for user-confirmed title, summary, outline, hook, quote lines, style, word count, and publish scope.
4. Trigger backend jobs through `aimagician_run_article_action`.
5. Publish through `aimagician_publish_missing_platforms`.
6. Read URL, draft ID, blocker, warning, and prompt-chain evidence from AImagician.

