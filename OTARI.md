# RunFix coding agent, routed through Otari

**Mozilla "Developers Wilding: Online" hackathon (Oct 28 – Nov 11, 2026)**
Branch: `wilding-otari`

The project named in the hackathon sign-up email is RunFix: an AI coding
agent that turns GitHub issues into pull requests. This repo is that agent's
public test playground (issue → agent → PR, test code only). In Otari
mode — the `agent-otari` workflow below, or the local env from
`.env.example` — **every model call the agent makes goes through the
hosted Otari gateway** (Mozilla.ai) instead of a single provider's API.
The original `agent` workflow still talks to its provider directly.

## What changed

- `.github/agent/run.py`
  - The model client is now gateway-agnostic: `LLM_BASE_URL`,
    `LLM_API_KEY`, `LLM_MODEL` come from the environment, so the same agent
    runs against Otari (`https://api.otari.ai/v1`) with an `otk_` workspace
    token. The original IteraCompute setup keeps working unchanged.
  - `ModelRouter`: if the primary model fails with a transient error
    (timeout, connection failure, rate limit, 5xx), the run switches to
    `LLM_FALLBACK_MODEL` — a model from a *different provider* reached
    through the same Otari endpoint — and stays on it. Client-side and
    4xx errors propagate immediately instead of burning a second call.
    One endpoint, no provider lock-in, no code change to fail over.
  - Hardening in the same file: the `bash` tool's subprocess environment
    is scrubbed of secrets, and the file tools enforce the repo-only /
    no-`.github/` / no-dotfiles rules in code (see Token safety).
  - `UsageTracker`: each successful response's token usage is logged per
    call and written to `.agent_usage.json`, and a totals line is appended
    to the agent summary that lands in the pull request. If a fallback
    occurred, the summary flags that the totals cover received responses
    only — a failed call's tokens are invisible to the client.
- `.github/workflows/agent-otari.yml`
  - Same issue→PR flow as the original workflow, triggered by the
    `agent-otari` label, with Otari as the gateway. Model and fallback are
    repository variables (`OTARI_MODEL`, `OTARI_FALLBACK_MODEL`); the token
    is the `OTARI_API_KEY` repository secret.
- `tests/test_otari_routing.py` — offline tests for the router and usage
  tracker (no network, no real key).

## Otari features used

- Hosted Otari gateway at `https://api.otari.ai/v1` (OpenAI-compatible).
- Workspace API token (`otk_…`) — the app only ever holds the gateway
  token, never a provider key.
- Multi-provider model choice through one endpoint, including open-weight
  models (defaults: `deepseek/deepseek-v4-pro-0813` primary,
  `openai/gpt-4o-mini` fallback; both overridable by repo variables).
- Client-side failover routing across providers via the gateway.
- Usage observability: per-call token usage from gateway responses,
  written into the pull request.

Provided by the Otari workspace — platform capabilities this project
relies on but has not yet verified in a live run:

- Usage also appears in the Otari dashboard's Usage tab.
- The workspace wallet caps what the token can spend in total.

## Token safety

The agent process itself must hold the gateway token to call Otari, so
the token is treated as scoped and revocable, and the code limits where
it can leak:

- The `bash` tool runs with a scrubbed environment: every variable whose
  name contains KEY, TOKEN, SECRET, or PASSWORD is removed, so a shell
  the model controls cannot read the token from `env`.
- The file tools enforce in code (not just in the AGENT.md prompt) that
  paths stay inside the repo and never touch `.github/` or dotfiles.
- `.agent_summary.txt` and `.agent_usage.json` are intentionally
  committed on PR branches as run evidence; they contain no credentials
  (the summary can contain agent error tracebacks).
- Residual risk, stated plainly: the agent's task text comes from GitHub
  issues, so prompt injection is possible — keep the workspace token
  spend-capped and revoke it if a run looks wrong.

## Run it locally

```bash
pip install openai
cp .env.example .env   # then put your otk_ token in it — never commit it
set -a; . ./.env; set +a
AGENT_TASK="Fix the bug: total() in app/calc.py skips the last item" \
  python3 .github/agent/run.py
python3 tests/test_calc.py          # verify the fix
python3 tests/test_otari_routing.py # offline routing/usage tests
```

## Run it on GitHub

1. Add the repository secret `OTARI_API_KEY` (your `otk_` workspace token).
2. Open an issue describing a small fix in `app/` and add the
   `agent-otari` label.
3. The agent runs through Otari and opens a PR whose body includes the
   agent summary and the token usage the gateway reported.

## Status

- [x] Gateway routing, failover, and usage tracking implemented + tested offline
- [ ] Live run through Otari with a real workspace token
- [ ] Live `agent-otari` issue → PR run on GitHub
- [ ] Demo video + hackathon feedback (see submission email, due Nov 11)

## Feedback for the Otari team

_To be completed from the live runs — what worked, what didn't, what was
missing. Drafted honestly from real usage, not in advance._
