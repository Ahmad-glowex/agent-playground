"""Tests for the Otari routing helpers in .github/agent/run.py.

Run with: python tests/test_otari_routing.py
No network and no real API key: run.py is loaded with a fake key and the
router is exercised against fake create functions.
"""
import importlib.util
import os
import subprocess
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


def transient(name="RateLimitError", code=None):
    """Build a fake transient provider error (matched by class name or
    by a 5xx status_code, mirroring the openai client's error types)."""
    e = type(name, (Exception,), {})("boom")
    if code is not None:
        e.status_code = code
    return e


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
            raise transient()
        return "ok"

    r = ModelRouter(create, "primary", "fallback")
    assert r.create() == "ok"
    assert r.switched is True
    assert r.model == "fallback"
    # Second call goes straight to the fallback, no retry of primary.
    assert r.create() == "ok"
    assert seen == ["primary", "fallback", "fallback"]


def test_router_falls_back_on_5xx():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        if model == "primary":
            raise transient("APIStatusError", code=503)
        return "ok"

    r = ModelRouter(create, "primary", "fallback")
    assert r.create() == "ok"
    assert seen == ["primary", "fallback"]


def test_router_does_not_fall_back_on_client_bug():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        raise ValueError("bad payload built locally")

    r = ModelRouter(create, "primary", "fallback")
    try:
        r.create()
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError to propagate")
    assert seen == ["primary"]
    assert r.switched is False


def test_router_does_not_fall_back_on_4xx():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        raise transient("APIStatusError", code=401)

    r = ModelRouter(create, "primary", "fallback")
    try:
        r.create()
    except Exception:
        pass
    else:
        raise AssertionError("expected the 401 to propagate")
    assert seen == ["primary"]
    assert r.switched is False


def test_router_reraises_without_fallback():
    def create(model=None, **kw):
        raise transient()

    r = ModelRouter(create, "primary", "")
    try:
        r.create()
    except Exception:
        pass
    else:
        raise AssertionError("expected the error to propagate")
    assert r.switched is False


def test_router_reraises_when_fallback_also_fails():
    def create(model=None, **kw):
        raise transient(code=503)

    r = ModelRouter(create, "primary", "fallback")
    try:
        r.create()
    except Exception:
        pass
    else:
        raise AssertionError("expected the error to propagate")
    assert r.switched is True
    assert r.model == "fallback"


def test_router_same_model_guard():
    seen = []

    def create(model=None, **kw):
        seen.append(model)
        raise transient()

    r = ModelRouter(create, "only", "only")
    try:
        r.create()
    except Exception:
        pass
    else:
        raise AssertionError("expected the error to propagate")
    assert seen == ["only"]
    assert r.switched is False


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


def test_usage_handles_partial_usage():
    t = UsageTracker()
    t.record("m1", SimpleNamespace(total_tokens=7))
    totals = t.totals()
    assert totals["calls"] == 1
    assert totals["total_tokens"] == 7
    assert totals["prompt_tokens"] == 0
    assert totals["per_call"][0]["prompt_tokens"] is None


def _probe_run_py(extra_env):
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print(m.API_KEY)\n"
    )
    env = {"AGENT_TASK": "probe",
           "PATH": os.environ.get("PATH", ""),
           "HOME": os.environ.get("HOME", "")}
    env.update(extra_env)
    out = subprocess.run([sys.executable, "-c", code, RUN_PY],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_env_precedence_generic_key_wins():
    key = _probe_run_py({"LLM_API_KEY": "generic",
                         "ITERACOMPUTE_API_KEY": "itera"})
    assert key == "generic", key


def test_env_precedence_iteracompute_still_works():
    key = _probe_run_py({"ITERACOMPUTE_API_KEY": "itera"})
    assert key == "itera", key


if __name__ == "__main__":
    test_router_uses_primary_when_it_works()
    test_router_falls_back_and_sticks()
    test_router_falls_back_on_5xx()
    test_router_does_not_fall_back_on_client_bug()
    test_router_does_not_fall_back_on_4xx()
    test_router_reraises_without_fallback()
    test_router_reraises_when_fallback_also_fails()
    test_router_same_model_guard()
    test_usage_totals()
    test_usage_handles_missing_usage()
    test_usage_handles_partial_usage()
    test_env_precedence_generic_key_wins()
    test_env_precedence_iteracompute_still_works()
    print("all tests passed")
