#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["claude-agent-sdk==0.2.163"]
# ///
"""Agent SDK smoke test and cost probe for the INSTALLED stack: makes real, billed API calls, so it is
run by the user, never by pytest (the name has no test_ prefix). Untested in the build sandbox, which
cannot reach the API.

    uv run --script tests/sdk_smoke.py [--runs 2] [--config ~/.claude]

Per setup (bare: no settings, default prompt; stack: setting_sources user/project/local, the scout
agent as main thread; blackcat: the stack's default main thread) and run: seconds to the first SDK
message (cold start: CLI, settings, hooks, MCP), total seconds, turns, cost, and the input / cache
write / cache read tokens of every model (ResultMessage.model_usage, subagents included). The second
run of a setup should read the cached prefix (cache read > 0): the system prompt is static
(exclude_dynamic_sections). Exits 1 if a blackcat run (JSON reports on) does not end in the JSON report.
"""
import argparse, asyncio, dataclasses, importlib.util, os, sys

PROMPT = "Reply with exactly: ok"


def helper(config):
    path = os.path.join(os.path.expanduser(config), "bin", "stack_sdk.py")
    spec = importlib.util.spec_from_file_location("stack_sdk", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tokens(model_usage):
    t = [0, 0, 0, 0]
    for u in (model_usage or {}).values():
        for i, k in enumerate(("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")):
            t[i] += int(u.get(k) or 0)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--config", default=os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
    a = ap.parse_args()
    s = helper(a.config)
    setups = {"bare": dataclasses.replace(s.options(None, max_turns=2, budget_usd=0.5), setting_sources=[]),
              "stack": s.options("scout", max_turns=2, budget_usd=0.5),
              "blackcat": s.options("blackcat", max_turns=2, budget_usd=0.5, json_reports=True)}
    print("| setup | run | first msg s | total s | turns | cost USD | input | cache write | cache read | output | report |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    bad = 0
    for name, opts in setups.items():
        for i in range(1, a.runs + 1):
            out = asyncio.run(s.run(PROMPT, opts))
            t = tokens(out.get("model_usage"))
            rep = out["report"]
            print("| %s | %d | %s | %.1f | %s | %s | %d | %d | %d | %d | %s/%s |" % (
                name, i, out.get("first_message_s"), (out.get("duration_ms") or 0) / 1000,
                out.get("num_turns"), out.get("total_cost_usd"), *t, rep["format"], rep["status"]))
            bad += name == "blackcat" and rep["format"] != "json"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
