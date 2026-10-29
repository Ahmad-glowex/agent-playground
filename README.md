# agent-playground

Test playground for our own coding agent: **GitHub Issue → agent → PR**.

How it works: open an issue, add the `agent` label, and a GitHub Actions
workflow runs a small coding agent. The agent reads the issue, edits the
code, runs the tests, and opens a pull request for review.

> ⚠️ The agent's model API is a free shared provider (IteraCompute).
> Do NOT put private code, secrets, or personal data in this repo or
> in its issues. Test code only.

## Otari mode (Mozilla Developers Wilding hackathon)

The same agent also runs in an Otari mode (the `wilding-otari` branch,
merged to `main` because GitHub only triggers issue-label workflows from
the default branch): under the `agent-otari` workflow, **all its model
calls are routed through the Otari gateway** (Mozilla.ai). Add the
`agent-otari` label to an issue instead of `agent`. It adds
cross-provider failover (primary model → fallback model through the same
gateway endpoint), per-call token-usage and cost reporting in the PR,
and a guard for a gateway quirk we found the hard way: the gateway's
front-end WAF rejects issue text that quotes a function call in markdown
inline code, so the agent unwraps exactly those spans before sending.
Full story, evidence, and feedback: [OTARI.md](OTARI.md).
Worked example: issue #3 → PR #7. Findings filed upstream:
[mozilla-ai/otari#2704](https://github.com/mozilla-ai/otari/issues/2704) (WAF 403),
[mozilla-ai/otari#2705](https://github.com/mozilla-ai/otari/issues/2705) (docs vs live gateway).
