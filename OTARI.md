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
  - `UsageTracker`: each successful response's token usage — and the
    per-call `cost_usd` the gateway reports — is logged per call and
    written to `.agent_usage.json`, and a totals line (with tracked
    cost, and a coverage note when only some calls reported a cost) is
    appended to the agent summary that lands in the pull request. If a
    fallback occurred, the summary flags that the totals cover received
    responses only — a failed call's tokens are invisible to the client.
  - `waf_safe` guard: on Otari runs, markdown inline code that wraps a
    function call is unwrapped in the task text and in tool results
    before they are sent to the gateway, because the gateway's front-end
    WAF rejects exactly that shape with a bare 403 (see Feedback). The
    rewrite is span-by-span (it can never merge spans) and idempotent.
    Model-authored text and tool-call arguments are deliberately NOT
    rewritten — changing them would corrupt files the agent writes —
    so they remain a theoretical residual risk, stated plainly.
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
- Usage observability: per-call token usage and cost from gateway
  responses, written into the pull request.
- A WAF-compatibility rewrite (`waf_safe`) for the gateway's front-end
  filter described under Feedback.

Provided by the Otari workspace — verified in the dashboard on
2026-10-29 after the runs above:

- The dashboard Usage tab shows the runs: 37 requests, 40.6k billed
  tokens, $0.02 tracked cost (Sep 29 – Oct 29), and the wallet shows
  $1.98 of $2.00 remaining, so the wallet does cap what the token can
  spend in total. One caveat for the Otari team: the WAF-blocked
  requests never reach the gateway, so they are invisible in Usage —
  the dashboard's 2.7% error rate does not include them.

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
- [x] Live `agent-otari` issue → PR run on GitHub — 2026-10-29, after
      merging this branch to `main` (GitHub only triggers issue-label
      workflows from the default branch): issue #3 → PR #7
      (https://github.com/Ahmad-glowex/agent-playground/pull/7),
      8 gateway calls, 16,189 tokens, tests green. Honest nuance: the
      deliberate bug had already been fixed on `main` by an earlier PR,
      so the agent refactored an already-correct loop; the demo video
      will re-run the flow against a reintroduced bug.
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
- **The gateway's front-end WAF rejects ordinary coding-agent traffic.**
  Three consecutive GitHub Actions agent runs died on their first call
  with `PermissionDeniedError: 403` and zero tokens used, while identical
  calls succeeded from a local machine. Root-caused by bisecting the
  request content from the runner itself: the block is an AWS ALB/WAF in
  front of the API (`server: awselb/2.0`, bare HTML "403 Forbidden"
  page, no JSON error body), and the trigger is **markdown inline code
  containing a function call** in the message text. Requests containing
  `` `total()` `` or `` `total([1, 2, 3])` `` are blocked; the same text
  without backticks, a backticked file path (`` `app/calc.py` ``), and a
  backticked shell command (`` `ls -la` ``) all pass. GitHub issue
  bodies — the natural input for a coding agent — routinely contain
  inline code like this, so the gateway currently cannot serve a real
  issue→PR agent without rewriting the user's words first. The failure
  is also misleading: SDKs surface the HTML page as a *permission* error,
  which sends you debugging your API key, not your prose. A JSON error
  naming the WAF rule would have saved hours.
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

**Still to add:** whether I would keep using Otari unprompted
(Tashfiq's own call, for the submission).
