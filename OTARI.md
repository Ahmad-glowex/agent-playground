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
    runs against Otari (`https://api.otari.ai/api/v1`) with an `otk_` workspace
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

- Hosted Otari gateway at `https://api.otari.ai/api/v1` (OpenAI-compatible).
- Workspace API token (`otk_…`) — the app only ever holds the gateway
  token, never a provider key.
- Multi-provider model choice through one endpoint, including open-weight
  models (defaults: `deepseek/deepseek-v4-pro-0813` primary,
  `bedrock:amazon.nova-lite-v1:0` fallback; both overridable by repo variables).
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
- [x] Live run through Otari with a real workspace token — 2026-10-29:
      the agent fixed the deliberate `total()` bug end-to-end via
      `deepseek/deepseek-v4-pro-0813` (7 gateway calls, 12,700 tokens,
      tests passing; usage record in the run's `.agent_usage.json`)
- [ ] Live `agent-otari` issue → PR run on GitHub (the workflow must be
      on the default branch for GitHub to trigger it from an issue label)
- [ ] Demo video + hackathon feedback (see submission email, due Nov 11)

## Feedback for the Otari team

From the live runs on 2026-10-29 (kept honest — good and bad):

**What worked**
- Drop-in swap: the agent already spoke the OpenAI API, so pointing
  `base_url` at Otari was the whole integration. Tool calling worked
  first try on `deepseek/deepseek-v4-pro-0813`.
- Every response carries `cost_usd` / `estimated_cost` — cost
  observability without a second API call.
- When I used the wrong base path, the gateway's error message itself
  named the correct one. More APIs should fail this helpfully.

**What didn't work**
- The Quickstart and blog examples point at `https://api.otari.ai/v1`,
  but the live gateway serves `/api/v1` — the docs' path 404s (with the
  helpful pointer above). Docs and gateway disagree.
- `GET /api/v1/models` lists 197 models but does **not** include
  `deepseek/deepseek-v4-pro-0813`, which the same workspace can
  successfully call. It is hard to trust the list as the source of what
  is available.
- A fresh workspace has no OpenAI provider configured
  (`provider_not_configured`), so the docs' example fallback
  (`openai/gpt-4o-mini`) fails out of the box; I had to discover a
  working fallback (`bedrock:amazon.nova-lite-v1:0`) by trial.
- The workspace key is shown exactly once at creation with no way to
  reveal it again; in an agent-driven browser session the value was
  effectively trapped (the agent could not relay it, and clipboard
  contents did not cross to the user's phone), forcing a second key to
  be created on the user's own phone instead. A "reveal again after
  re-auth" option would have saved it.

**Still to add after the GitHub-side run:** dashboard Usage tab and
wallet behaviour, and whether I would keep using Otari unprompted.
