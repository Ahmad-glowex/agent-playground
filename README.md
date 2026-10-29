# agent-playground

Test playground for our own coding agent: **GitHub Issue → agent → PR**.

How it works: open an issue, add the `agent` label, and a GitHub Actions
workflow runs a small coding agent. The agent reads the issue, edits the
code, runs the tests, and opens a pull request for review.

> ⚠️ The agent's model API is a free shared provider (IteraCompute).
> Do NOT put private code, secrets, or personal data in this repo or
> in its issues. Test code only.

## Otari mode (Mozilla Developers Wilding hackathon)

On the `wilding-otari` branch the same agent runs with **all model calls
routed through the Otari gateway** (Mozilla.ai): add the `agent-otari`
label to an issue instead of `agent`. It adds cross-provider failover
(primary model → fallback model through the same gateway endpoint) and
per-call token-usage reporting in the PR. See [OTARI.md](OTARI.md).
