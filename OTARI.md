# RunFix coding agent, routed through Otari

**Mozilla "Developers Wilding: Online" hackathon (Oct 28 – Nov 11, 2026)**
Branch: `wilding-otari`

The project named in the hackathon sign-up email is RunFix: an AI coding
agent that turns GitHub issues into pull requests. This repo is that agent's
public test playground (issue → agent → PR, test code only). For this
hackathon, **every model call the agent makes goes through the hosted Otari
gateway** (Mozilla.ai) instead of a single provider's API.

## What changed

- `.github/agent/run.py`
  - The model client is now gateway-agnostic: `LLM_BASE_URL`,
    `LLM_API_KEY`, `LLM_MODEL` come from the environment, so the same agent
    runs against Otari (`https://api.otari.ai/v1`) with an `otk_` workspace
    token. The original IteraCompute setup keeps working unchanged.
  - `ModelRouter`: if the primary model errors at the gateway/provider,
    the run switches to `LLM_FALLBACK_MODEL` — a model from a *different
    provider* reached through the same Otari endpoint — and stays on it.
    One endpoint, no provider lock-in, no code change to fail over.
  - `UsageTracker`: every response's token usage is logged per call and
    written to `.agent_usage.json`, and a totals line is appended to the
    agent summary that lands in the pull request.
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
  mirrored in the Otari dashboard's Usage tab.
- Workspace wallet/budget on the Otari side caps what a run can spend.

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
