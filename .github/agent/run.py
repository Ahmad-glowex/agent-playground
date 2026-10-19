#!/usr/bin/env python3
"""Minimal coding agent: GitHub issue in, code changes out.

Uses any OpenAI-compatible chat API with tool calling. The workflow
commits whatever changed and opens a pull request afterwards.
"""
import glob as globlib
import json
import os
import subprocess
import sys
import traceback

from openai import OpenAI

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.iteracompute.com/v1")
API_KEY = os.environ["ITERACOMPUTE_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3.8-27b")
TASK = os.environ["AGENT_TASK"]
REPO = os.environ.get("AGENT_REPO", os.getcwd())
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "25"))

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def sh(cmd, timeout=120):
    p = subprocess.run(
        cmd, shell=True, cwd=REPO, capture_output=True, text=True, timeout=timeout
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


def call_tool(name, args):
    if name == "read_file":
        with open(os.path.join(REPO, args["path"])) as f:
            return f.read()[-6000:]
    if name == "write_file":
        p = os.path.join(REPO, args["path"])
        os.makedirs(os.path.dirname(p) or REPO, exist_ok=True)
        with open(p, "w") as f:
            f.write(args["content"])
        return f"wrote {args['path']}"
    if name == "edit_file":
        p = os.path.join(REPO, args["path"])
        with open(p) as f:
            s = f.read()
        if args["old"] not in s:
            return "ERROR: old text not found in file"
        with open(p, "w") as f:
            f.write(s.replace(args["old"], args["new"], 1))
        return f"edited {args['path']}"
    if name == "glob":
        hits = globlib.glob(args["pattern"], root_dir=REPO, recursive=True)
        return "\n".join(hits)[:3000] or "(no matches)"
    if name == "bash":
        return sh(args["command"])
    raise ValueError(f"unknown tool {name}")


def main():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENT.md")) as f:
        system = f.read()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"TASK (from GitHub issue):\n{TASK}"},
    ]
    summary = None
    try:
        for step in range(MAX_STEPS):
            r = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS,
                tool_choice="auto", temperature=0.2, max_tokens=2048,
            )
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
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": out})
                print(f"[step {step}] {tname} -> {out[:160]}", flush=True)
            if summary is not None:
                break
    except Exception:  # noqa: BLE001
        summary = (summary or "") + "\nAgent crashed:\n" + traceback.format_exc()[-2000:]
    summary = summary or "Agent finished without calling done()."
    print("SUMMARY:", summary, flush=True)
    with open(os.path.join(REPO, ".agent_summary.txt"), "w") as f:
        f.write(summary)


if __name__ == "__main__":
    main()
