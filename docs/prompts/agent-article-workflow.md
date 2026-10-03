# Agent Article Workflow Prompt Source

Purpose: constrain article conversations so the agent advances AImagician state instead of inventing local flow state.

## Conversation Contract

- Topic selection is separate from article generation.
- The agent must confirm style, target word count, publish scope, title, summary, outline, quote lines, and opening hook before body generation when the user provides or edits them.
- User-confirmed fields are authoritative overrides.
- Existing articles are resolved by Postgres article search and publication matrix, not by asking for Notion IDs.
- Preview means Hexo plus WeChat draft unless the user chooses a different scope.
- Full-network publish only fills missing platforms and skips existing published/draft states by default.

## Quality Contract

- Body generation must use research evidence unless the user explicitly chooses an opinion-only piece.
- Warnings are recorded as quality findings and fed back into prompt/runtime improvement.
- Repair jobs are not the default answer to every quality issue; improve the producing stage when repeated warnings appear.

