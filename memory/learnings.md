# Agent learnings

Durable lessons written by the coding agent itself, one run teaching the
next. Each entry is dated and tied to the issue it came from.

Rules: short bullets only, no trivia, NEVER secrets/keys/tokens/personal
data. (The agent's system prompt enforces this; this file is committed to
main by the workflow after every run, even when the code PR is not merged.)

## 2026-10-21 — memory system created
- Memory convention started: read memory/*.md at task start, append
  durable learnings here before done.

## 2026-10-21 — issue: total() skips last item
- Off-by-one bug pattern: `range(len(items))` skips the last element.
  Prefer iterating directly (`for item in items`) over index loops.
- `range(len(items) + 1)` is NOT a valid fix — it indexes out of bounds.
