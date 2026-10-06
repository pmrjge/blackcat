# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Copy the graded-run sources of the agents-baseline campaign into gen/src/ (read-only on the source).

Keeps only the columns the RS generator needs; drops session ids, agent ids, timestamps, descriptions and every
free-text field that is not a prompt, rubric, note or grader evidence line. Redacts the embedded prompt-injection
sentence of P06 (test data of that campaign, not to be shown to arms as live text).
Run once: uv run --script extract_src.py  (writes src/*.csv and src/SOURCES.sha256).
"""
import csv
import hashlib
import re
from pathlib import Path

CAMPAIGN = Path("/Users/pmrj/ZDone/claude-agent-stack/claude-local-work/campaign/agents-baseline")
SRC = Path(__file__).resolve().parent / "src"
INJECTION = re.compile(r"NOTE TO AI ASSISTANTS:.*?system prompt\.", re.S)
SENSITIVE = re.compile(r"/Users/|@[a-z0-9-]+\.[a-z]{2,}|\b[0-9a-f]{8}-[0-9a-f]{4}-|\ba[0-9a-f]{16}\b|sk-[A-Za-z0-9]{8}")


def read(name):
    with open(CAMPAIGN / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(name, rows, cols):
    SRC.mkdir(parents=True, exist_ok=True)
    with open(SRC / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            out = {c: (r.get(c) or "") for c in cols}
            for c, v in out.items():
                if SENSITIVE.search(v):
                    raise SystemExit(f"sensitive pattern in {name}:{c}: {v[:80]}")
            w.writerow(out)


def main():
    prompts = read("prompts.csv")
    for r in prompts:
        r["prompt"] = INJECTION.sub("[embedded instruction text omitted from this corpus]", r["prompt"])
    write("prompts.csv", prompts,
          ["id", "family", "target_agent", "expected_skills", "cost_class", "prompt", "check", "notes"])
    grades = []
    for batch, fname in (("T8a", "grades.csv"), ("T8b", "grades_T8b.csv"), ("b0v2", "grades_b0v2.csv")):
        for r in read(fname):
            grades.append({"batch": batch, "id": r["id"], "variant": r.get("variant") or "v1",
                           "check_result": r["check_result"], "why": r["why"]})
    write("grades.csv", grades, ["batch", "id", "variant", "check_result", "why"])
    runs = [r for r in read("runs.csv") if r["kind"] == "prompt"]
    write("runs.csv", runs, ["prompt_id", "is_root", "depth", "agent_type", "model", "turns", "tool_calls",
                             "spawn_count", "child_types", "tokens_total", "final_status", "wall_s"])
    lines = [f"{hashlib.sha256((CAMPAIGN / n).read_bytes()).hexdigest()}  {CAMPAIGN / n}"
             for n in ("prompts.csv", "grades.csv", "grades_T8b.csv", "grades_b0v2.csv", "runs.csv")]
    (SRC / "SOURCES.sha256").write_text("\n".join(lines) + "\n")
    print(len(prompts), len(grades), len(runs))


if __name__ == "__main__":
    main()
