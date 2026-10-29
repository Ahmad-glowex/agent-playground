#!/usr/bin/env python3
"""Minimal coding agent: GitHub issue in, code changes out.

Uses any OpenAI-compatible chat API with tool calling. The workflow
commits whatever changed and opens a pull request afterwards.
"""
import glob as globlib
import json
import os
import re
import subprocess
import sys
import traceback
from urllib.parse import urlparse

from openai import OpenAI

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.iteracompute.com/v1")
# LLM_API_KEY is the generic name (used for the Otari gateway token);
# ITERACOMPUTE_API_KEY stays supported for the original workflow.
API_KEY = os.environ.get("LLM_API_KEY") or os.environ["ITERACOMPUTE_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3.8-27b")
FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "")
TASK = os.environ["AGENT_TASK"]
REPO = os.environ.get("AGENT_REPO", os.getcwd())
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "25"))

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def _usage_cost(usage):
    """The Otari gateway reports a per-call cost (cost_usd) in the usage
    object; the SDK keeps unknown fields in model_extra. Returns a float
    or None when the provider reports no cost."""
    raw = getattr(usage, "cost_usd", None)
    if raw is None:
        extra = getattr(usage, "model_extra", None) or {}
        raw = extra.get("cost_usd")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


class UsageTracker:
    """Accumulates per-call token usage reported by the gateway."""

    def __init__(self):
        self.calls = []

    def record(self, model, usage):
        entry = {
            "model": model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "cost_usd": _usage_cost(usage),
        }
        self.calls.append(entry)
        cost = f", ${entry['cost_usd']:.6f}" if entry["cost_usd"] is not None else ""
        print(f"[usage] {model}: {entry['total_tokens']} total tokens{cost}",
              flush=True)

    def totals(self):
        costs = [c["cost_usd"] for c in self.calls if c["cost_usd"] is not None]
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in self.calls),
            "completion_tokens": sum(c["completion_tokens"] or 0 for c in self.calls),
            "total_tokens": sum(c["total_tokens"] or 0 for c in self.calls),
            "total_cost_usd": round(sum(costs), 6) if costs else None,
            "costed_calls": len(costs),
            "per_call": self.calls,
        }


def _is_transient_error(e):
    """True for errors where retrying on another provider can help:
    timeouts, connection failures, rate limits, and 5xx responses.
    Client-side bugs and 4xx responses are not transient — the same
    token and payload would fail identically on the fallback."""
    names = {c.__name__ for c in type(e).__mro__}
    if names & {"APITimeoutError", "APIConnectionError", "RateLimitError"}:
        return True
    code = getattr(e, "status_code", None)
    return isinstance(code, int) and code >= 500


class ModelRouter:
    """Calls the primary model; on a transient gateway/provider error,
    switches to the fallback model (a different provider via the same
    gateway) and stays on it for the rest of the run. Non-transient
    errors, and any error with no fallback configured, propagate."""

    def __init__(self, create_fn, primary, fallback=""):
        self._create = create_fn
        self.model = primary
        self.fallback = fallback
        self.switched = False

    def create(self, **kwargs):
        try:
            return self._create(model=self.model, **kwargs)
        except Exception as e:
            if (not self.fallback or self.switched
                    or self.model == self.fallback
                    or not _is_transient_error(e)):
                raise
            print(f"[router] {self.model} failed ({type(e).__name__}: "
                  f"{str(e)[:200]}); switching to fallback "
                  f"{self.fallback}", flush=True)
            self.model = self.fallback
            self.switched = True
            return self._create(model=self.model, **kwargs)


usage = UsageTracker()
router = ModelRouter(client.chat.completions.create, MODEL, FALLBACK_MODEL)


_SPAN = re.compile(r"`([^`\n]+)`")


def waf_safe(text):
    """Unwrap markdown inline code whose content contains a call.

    The Otari gateway's front-end WAF rejects message text containing
    spans like `total()` or `total([1, 2, 3])` with a bare HTML 403
    (root-caused 2026-10-29; evidence in OTARI.md). Dropping the
    backticks around exactly those spans keeps the meaning and lets the
    request through. Matching is span-by-span, so a rewrite can never
    merge two spans or leave a new blocked span behind, and applying it
    twice changes nothing the second time. Inline code without a "("
    (most file paths, shell commands) is untouched; a parenthesised
    filename would lose its backticks too, which is cosmetic only.
    Returns (text, rewrites).
    """
    rewrites = 0

    def _unwrap(match):
        nonlocal rewrites
        inner = match.group(1)
        if "(" in inner:
            rewrites += 1
            return inner
        return match.group(0)

    return _SPAN.sub(_unwrap, text), rewrites


def _is_otari_url(url):
    """True when the base URL's host is Otari's (parsed, case-folded —
    a substring test would misfire on lookalike hosts)."""
    host = urlparse(url).hostname or ""
    return host == "api.otari.ai" or host.endswith(".otari.ai")


_SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _scrubbed_env():
    """Environment for the agent's bash tool: everything except secrets.
    The gateway token must never reach a shell the model controls."""
    return {k: v for k, v in os.environ.items()
            if not any(m in k.upper() for m in _SECRET_ENV_MARKERS)}


def sh(cmd, timeout=120):
    p = subprocess.run(
        cmd, shell=True, cwd=REPO, capture_output=True, text=True,
        timeout=timeout, env=_scrubbed_env()
    )
    out = (p.stdout + p.stderr)[-4000:]
    return f"$ {cmd}\n(exit {p.returncode})\n{out}"


TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the repo.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace the first exact occurrence of old text with new text in a file.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "old": {"type": "string"},
                                      "new": {"type": "string"}},
                       "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "glob",
        "description": "List repo files matching a glob pattern, e.g. '**/*.py'.",
        "parameters": {"type": "object",
                       "properties": {"pattern": {"type": "string"}},
                       "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a shell command in the repo root (run tests, reproduce bugs).",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "done",
        "description": "Call when the task is complete. Summarize changes and test results.",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]}}},
]


def _safe_path(rel):
    """Resolve a tool path inside the repo, refusing escapes, the
    .github/ directory, and dotfiles. AGENT.md states these rules;
    this enforces them in code instead of trusting the prompt."""
    root = os.path.realpath(REPO)
    p = os.path.realpath(os.path.join(root, rel))
    if p != root and not p.startswith(root + os.sep):
        raise ValueError(f"path escapes the repo: {rel}")
    parts = [part for part in os.path.relpath(p, root).split(os.sep)
             if part not in (".", "")]
    if any(part.startswith(".") for part in parts):
        raise ValueError(f"dotfiles and .github/ are off-limits: {rel}")
    return p


def call_tool(name, args):
    if name == "read_file":
        with open(_safe_path(args["path"])) as f:
            return f.read()[-6000:]
    if name == "write_file":
        p = _safe_path(args["path"])
        os.makedirs(os.path.dirname(p) or REPO, exist_ok=True)
        with open(p, "w") as f:
            f.write(args["content"])
        return f"wrote {args['path']}"
    if name == "edit_file":
        p = _safe_path(args["path"])
        with open(p) as f:
            s = f.read()
        if args["old"] not in s:
            return "ERROR: old text not found in file"
        with open(p, "w") as f:
            f.write(s.replace(args["old"], args["new"], 1))
        return f"edited {args['path']}"
    if name == "glob":
        hits = globlib.glob(args["pattern"], root_dir=REPO, recursive=True)
        hits = [h for h in hits
                if not any(part.startswith(".") for part in h.split("/"))]
        return "\n".join(hits)[:3000] or "(no matches)"
    if name == "bash":
        return sh(args["command"])
    raise ValueError(f"unknown tool {name}")


def main():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENT.md")) as f:
        system = f.read()
    task_text = TASK
    if _is_otari_url(BASE_URL):
        task_text, rewritten = waf_safe(TASK)
        if rewritten:
            print(f"[waf-guard] rewrote {rewritten} inline-code span(s) "
                  "in the task text (gateway WAF compatibility)", flush=True)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TASK (from GitHub issue):\n{task_text}"},
    ]
    summary = None
    try:
        for step in range(MAX_STEPS):
            r = router.create(
                messages=messages, tools=TOOLS,
                tool_choice="auto", temperature=0.2, max_tokens=2048,
            )
            usage.record(router.model, getattr(r, "usage", None))
            m = r.choices[0].message
            messages.append(m)
            if not m.tool_calls:
                messages.append({"role": "user", "content":
                    "You made no tool call. Call a tool, or call done."})
                continue
            for tc in m.tool_calls:
                tname = tc.function.name
                try:
                    targs = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    targs = {}
                if tname == "done":
                    summary = targs.get("summary", "")
                    break
                try:
                    out = call_tool(tname, targs)
                except Exception as e:  # noqa: BLE001
                    out = f"ERROR: {e}"
                if _is_otari_url(BASE_URL):
                    # Tool results are resent in every later request body,
                    # so a file the agent reads (e.g. a markdown doc with
                    # inline-code calls) would re-arm the WAF trigger.
                    out, n = waf_safe(out)
                    if n:
                        print(f"[waf-guard] rewrote {n} inline-code "
                              "span(s) in a tool result", flush=True)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": out})
                print(f"[step {step}] {tname} -> {out[:160]}", flush=True)
            if summary is not None:
                break
    except Exception:  # noqa: BLE001
        summary = (summary or "") + "\nAgent crashed:\n" + traceback.format_exc()[-2000:]
    summary = summary or "Agent finished without calling done()."
    totals = usage.totals()
    summary += (f"\n\nModel usage (via {BASE_URL}): {totals['calls']} calls, "
                f"{totals['total_tokens']} total tokens"
                + (f", tracked cost ${totals['total_cost_usd']:.4f}"
                   if totals.get("total_cost_usd") is not None else "")
                + (f" (from {totals['costed_calls']} of {totals['calls']} calls)"
                   if totals.get("total_cost_usd") is not None
                   and totals.get("costed_calls", 0) < totals["calls"] else "")
                + f", final model {router.model}"
                + (" (fallback engaged)" if router.switched else "") + ".")
    if router.switched:
        summary += (" Note: totals cover received responses only; the "
                    "failed primary call may have consumed tokens the "
                    "client never saw.")
    print("SUMMARY:", summary, flush=True)
    with open(os.path.join(REPO, ".agent_summary.txt"), "w") as f:
        f.write(summary)
    with open(os.path.join(REPO, ".agent_usage.json"), "w") as f:
        json.dump({"base_url": BASE_URL,
                   "fallback_engaged": router.switched, **totals},
                  f, indent=2)


if __name__ == "__main__":
    main()
