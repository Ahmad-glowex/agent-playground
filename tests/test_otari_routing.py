"""Tests for the Otari routing helpers in .github/agent/run.py.

Run with: python tests/test_otari_routing.py
No network and no real API key: run.py is loaded with a fake key and the
router is exercised against fake create functions.
"""
import importlib.util
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("AGENT_TASK", "test task")
os.environ.setdefault("LLM_API_KEY", "otk_fake_for_tests")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(ROOT, ".github", "agent", "run.py")

spec = importlib.util.spec_from_file_location("agent_run", RUN_PY)
agent_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_run)

ModelRouter = agent_run.ModelRouter
UsageTracker = agent_run.UsageTracker


def test_router_uses_primary_when_it_works():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        return "ok"

    r = ModelRouter(create, "primary", "fallback")
    assert r.create() == "ok"
    assert seen == ["primary"]
    assert r.switched is False
    assert r.model == "primary"


def test_router_falls_back_and_sticks():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        if model == "primary":
            raise RuntimeError("provider down")
        return "ok"

    r = ModelRouter(create, "primary", "fallback")
    assert r.create() == "ok"
    assert r.switched is True
    assert r.model == "fallback"
    # Second call goes straight to the fallback, no retry of primary.
    assert r.create() == "ok"
    assert seen == ["primary", "fallback", "fallback"]


def test_router_reraises_without_fallback():
    def create(model=None, **kw):
        raise RuntimeError("provider down")

    r = ModelRouter(create, "primary", "")
    try:
        r.create()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")
    assert r.switched is False


def test_router_reraises_when_fallback_also_fails():
    def create(model=None, **kw):
        raise RuntimeError("all down")

    r = ModelRouter(create, "primary", "fallback")
    try:
        r.create()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")
    assert r.switched is True
    assert r.model == "fallback"


def test_usage_totals():
    t = UsageTracker()
    t.record("m1", SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                   total_tokens=15))
    t.record("m2", SimpleNamespace(prompt_tokens=3, completion_tokens=2,
                                   total_tokens=5))
    totals = t.totals()
    assert totals["calls"] == 2
    assert totals["prompt_tokens"] == 13
    assert totals["completion_tokens"] == 7
    assert totals["total_tokens"] == 20
    assert totals["per_call"][0]["model"] == "m1"


def test_usage_handles_missing_usage():
    t = UsageTracker()
    t.record("m1", None)
    totals = t.totals()
    assert totals["calls"] == 1
    assert totals["total_tokens"] == 0
    assert totals["per_call"][0]["total_tokens"] is None


if __name__ == "__main__":
    test_router_uses_primary_when_it_works()
    test_router_falls_back_and_sticks()
    test_router_reraises_without_fallback()
    test_router_reraises_when_fallback_also_fails()
    test_usage_totals()
    test_usage_handles_missing_usage()
    print("all tests passed")
