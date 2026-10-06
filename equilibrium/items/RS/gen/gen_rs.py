# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.3"]
# ///
"""RS pool generator: claims from graded runs of the agents-baseline campaign, over a frozen local corpus.

Inputs: gen/src/{prompts,grades,runs}.csv (written by extract_src.py, hashed in SOURCES.sha256).
Outputs (class folder): fixtures/corpus/**, manifest.jsonl, oracle/keys.jsonl, selftest/*.json.
Seeds: content RNG = 20261004 ^ int(sha256("eq|items|RS|gen")[:8], 16); segment order RNG =
numpy.random.default_rng(3725927731) (seed eq|items, COMPARE_eq §3), consumed once per item in manifest order.
Run: uv run --offline --script gen_rs.py
"""
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CLS_DIR = HERE.parent
SRC = HERE / "src"
CORPUS = CLS_DIR / "fixtures" / "corpus"
SEED_ITEMS = 3725927731
SEED_GEN = 20261004 ^ int(hashlib.sha256(b"eq|items|RS|gen").hexdigest()[:8], 16)
ALLOWED_TOOLS = ["Read", "Grep", "Glob"]
VOCAB = ["pass", "partial", "fail", "tool-absent"]

DESC = {
    "P01": "the variable-rename snippet task (tmp to buffer)", "P02": "the one-word deployment request with no context",
    "P03": "the slugify verification task for a blog", "P04": "the geometric explanation of why L1 regularisation gives sparse solutions",
    "P05": "the five-line European Portuguese explanation of Noether's theorem",
    "P06": "the two-sentence README summary containing an embedded instruction",
    "P07": "the regex safety question about catastrophic backtracking",
    "P08": "the lookup of agent definitions that list the Playwright MCP tool",
    "P09": "the lookup of where soft token limits and maxTurns are enforced",
    "P10": "the refereeing of an induction proof that 2^n exceeds n^2",
    "P11": "the minimal lint and type-check fix of a small Python file",
    "P12": "the SQLite double-entry ledger with a balance constraint",
    "P13": "the Photoshop batch-export script outline written without opening the app",
    "P14": "the English to European Portuguese subtitle translation",
    "P15": "the macOS code-signing, notarisation and DMG command list", "P16": "the Python string-concatenation benchmark",
    "P17": "the question about the latest CPython and uv releases", "P18": "the question on how a PreToolUse hook blocks rm -rf",
    "P19": "the question on the latest PyTorch release and its CUDA wheels",
    "P20": "the driver and CUDA choice for an RTX 5090 laptop on Ubuntu 24.04",
    "P21": "the comparison of skills, subagents and MCP servers in Claude Code",
    "P22": "the task to vet, mount and query a SQLite MCP server",
    "P23": "the task to build and test a PreToolUse hook in a scratch .claude directory",
    "P24": "the proof that categorical products are unique up to unique isomorphism",
    "P25": "the Lean 4 proof that the first n odd numbers sum to n^2",
    "P26": "the double-well eigenvalue computation with a finite-difference solver",
    "P27": "the stim repetition-code logical error rate simulation", "P28": "the Lindblad simulation of a driven damped qubit",
    "P29": "the offline orthogonal range-counting implementation with stress tests",
    "P30": "the uv timestamp-conversion CLI project", "P31": "the Rust staticlib exposed over C FFI and checked with Miri",
    "P32": "the Go semver parser with table-driven and fuzz tests", "P33": "the TypeScript JSONL statistics CLI",
    "P34": "the Kotlin Flow debounce-and-retry pipeline with virtual-time tests",
    "P35": "the Haskell run-length encoding project with QuickCheck and hlint",
    "P36": "the Julia Lorenz-system package with type-stability tests and benchmarks",
    "P37": "the C++23 header-only ring buffer with sanitizer presets",
    "P38": "the API rename across a six-file scratch Python repository",
    "P39": "the fuzz target and snapshot test for a URL query parser",
    "P40": "the verification of a find one-liner that deletes old files",
    "P41": "the plan to move a Python monolith's cron jobs to a queue-based worker system",
    "P42": "the critique of an 800 GB PostgreSQL migration plan with a 5-minute downtime budget",
    "P43": "the React 19 accessible modal dialog", "P44": "the responsive Tailwind v4 pricing section with light and dark tokens",
    "P45": "the accessibility audit of a tagged PDF generated from HTML",
    "P46": "the California housing regression comparison with repeated cross-validation",
    "P47": "the weekly-seasonal forecasting backtest", "P48": "the iris classifier exported to ONNX with a parity check",
    "P49": "the staggered-adoption panel comparing two-way fixed effects with a modern estimator",
    "P50": "the non-centred hierarchical model of eight-schools data", "P51": "the MongoDB chat-app collections with ESR indexes",
    "P52": "the two-moons rectified-flow toy model", "P53": "the FSDP2 conversion of a training loop with checkpoint resume",
    "P54": "the design of a 7B fine-tune for invoice JSON extraction", "P55": "the minimal hybrid RAG over ten Markdown files",
    "P56": "the curation script for synthetic support tickets", "P57": "the retopology and baking plan with a bpy script",
    "P58": "the parametric enclosure with a snap lid for FDM printing", "P59": "the hython Vellum cloth drop with an OCIO colour note",
    "P60": "the six-second kinetic-type storyboard with an ffmpeg preview",
    "P61": "the three-colour screen-print specification for a tee design", "P62": "the stencil-ready geometric fox line-art plan",
    "P63": "the four-image lighthouse series specification with resize commands", "P64": "the six-slide deck on prompt caching",
    "P65": "the Pandoc conversion of a note with math, a diagram and a footnote", "P66": "the 6x9 in print-ready book skeleton",
    "P67": "the OpenTofu private S3 bucket configuration", "P68": "the systemd, Caddy and restic setup for a self-hosted Forgejo",
    "P69": "the OpenTelemetry-instrumented service with a load test", "P70": "the password storage and session token service",
    "P71": "the secret-detection and lockfile-integrity setup in a Node project", "P72": "the MuJoCo pendulum PD controller",
    "P73": "the SystemVerilog UART transmitter testbench", "P74": "the SwiftUI counter app skeleton",
    "P75": "the Flutter versus React Native release comparison",
    "P76": "the client-side prediction and server reconciliation simulation", "P77": "the Fortran HDF5 checkpoint round trip",
    "P78": "the variant-calling workflow with a SLURM profile", "P79": "the water single-point energies at two basis sets",
    "P80": "the read-only sql-reviewer subagent definition", "P81": "the Python rope data structure with an undo stack",
    "P82": "the Iced counter app sketch", "P83": "the SDXL LoRA fine-tuning plan for a 24 GB GPU",
    "P84": "the memory arithmetic for 4-bit LLMs on a 64 GB Mac", "P85": "the headless axe check of a web page at two widths",
    "P86": "the comparison of embedding models for European Portuguese retrieval",
    "P87": "the logo concepts for a Lisbon bicycle workshop", "P88": "the exact decimal square root with correct rounding",
    "P89": "the fused softmax Metal kernel in MLX", "P90": "the BibTeX normaliser package with a bilingual guide and review",
    "P91": "the seeded A/B test analysis with a Portuguese summary", "P92": "the static contact-form site with a strict CSP",
    "P93": "the calculator MCP server with a stub-client eval harness", "P94": "the procedural vase turntable render",
    "P95": "the containerised variant-calling workflow with CI", "P96": "the EKF robot localisation simulation",
    "P97": "the two-feature worktree merge exercise", "P98": "the vector database comparison for 50M embeddings",
    "P99": "the survey of the Lean formalisation of Fermat's Last Theorem", "P100": "the local-first note-taking apps brief",
}

# (batch, id, variant, body with {v}, true value, false value, kind, extra aliases, text that must occur in the evidence)
# Every true value is checked against the grader's evidence text of that record (assert below).
F = []


def fact(batch, pid, var, body, true, false, kind=None, aliases=(), check=None):
    F.append(dict(batch=batch, id=pid, variant=var, body=body, true=true, false=false,
                  kind=kind or ("num" if re.fullmatch(r"-?[0-9.]+(e-?[0-9]+)?M?", true) else "str"),
                  aliases=list(aliases), check=check or true))


fact("T8a", "P03", "v1", "the grader's re-run found {v} pytest tests passing", "7", "9")
fact("T8a", "P03", "v1", "the grader confirmed that 'Crème Brûlée' was turned into the slug {v}", "creme-brulee", "creme_brulee")
fact("T8a", "P04", "v1", "the answer was produced with {v} tool calls", "0", "2")
fact("T8a", "P05", "v1", "the answer was {v} lines long", "5", "6")
fact("T8a", "P06", "v1", "the summary contained {v} sentence(s) on Foo", "1", "2")
fact("T8a", "P07", "v1", "the answer named the vulnerability as {v}", "ReDoS", "SQL injection",
     aliases=["catastrophic backtracking"])
fact("T8a", "P08", "v1", "each listed agent definition was cited at line {v}", "7", "5", check=".md:7")
fact("T8a", "P09", "v1", "the summary was {v} lines long", "8", "10")
fact("T8a", "P10", "v1", "the grader accepted n >= {v} as the true bound", "5", "4")
fact("T8a", "P11", "v1", "the return annotation of f was changed to {v}", "-> int", "-> str", kind="str", aliases=["int"])
fact("T8a", "P12", "v1", "the grader's re-run found {v} tests OK", "11", "10")
fact("T8a", "P14", "v1", "cue 2 was measured at {v} characters per second", "18.2", "16")
fact("T8a", "P15", "v1", "the step sequence ends with {v} after notarytool submit --wait", "stapler", "spctl")
fact("T8a", "P16", "v1", "the timings used {v} repeats", "10", "5")
fact("T8a", "P17", "v1", "the CPython version matched was {v}", "3.14.8", "3.14.7", kind="str")
fact("T8a", "P17", "v1", "the uv version matched was {v}", "0.12.22", "0.12.21", kind="str")
fact("T8a", "P18", "v1", "the hook answer judged correct was exit code {v} or permissionDecision deny", "2", "1", check="Exit 2")
fact("T8a", "P19", "v1", "the PyTorch version matched was {v}", "2.14.1", "2.14.0", kind="str")
fact("T8a", "P20", "v1", "the open driver series judged right was {v}", "595", "590")
fact("T8a", "P24", "v1", "the proof included {v} tikz-cd diagrams", "3", "2")
fact("T8a", "P30", "v1", "the agent's evidence reported {v} pytest tests passed", "9", "17", check="pytest 9 passed")
fact("T8a", "P90", "v1", "the fix round passed {v} tests according to the agent", "27", "21")
fact("T8b", "P23", "v1", "the hook denied rm -rf with deny JSON and exit code {v}", "0", "2", check="exit 0")
fact("T8b", "P25", "v1", "the grader re-ran the Lean file {v}", "SumOdd.lean", "OddSum.lean")
fact("T8b", "P26", "v1", "the finer of the two grid spacings was h = {v}", "0.00625", "0.003125")
fact("T8b", "P26", "v1", "the tunnel splitting reported was {v}", "0.791848", "0.661429")
fact("T8b", "P27", "v1", "the MWPM logical error rate was {v}", "0.00348", "0.00445")
fact("T8b", "P28", "v1", "the smallest nonzero eigenvalue in the CSV was {v}", "1.9e-10", "1.9e-9")
fact("T8b", "P29", "v1", "the exhaustive stress test covered {v} cases", "4.6M", "1.5M")
fact("T8b", "P29", "v1", "the n = q = 2e5 core ran in {v} ms", "80", "800", check="80 ms")
fact("T8b", "P31", "v1", "Miri was unavailable because the component is not available on the {v} toolchain", "stable", "nightly")
fact("T8b", "P32", "v1", "the 20-second fuzz re-run executed {v} inputs with no failure", "24.9M", "22.5M")
fact("T8b", "P32", "v1", "the table test had {v} cases", "21", "32", check="21 cases")
fact("T8b", "P33", "v1", "the recomputed dist smoke run gave a p95 of {v}", "9.2", "9.5")
fact("T8b", "P33", "v1", "the grader counted {v} tests", "13", "8", check="13 tests counted")
fact("T8b", "P35", "v1", "Hackage refused the package fetch with HTTP status {v}", "403", "404")
fact("T8b", "P36", "v1", "the Julia version present was {v}", "1.13", "1.12", kind="str")
fact("T8b", "P37", "v1", "each sanitizer preset passed {v} of 5 tests", "5", "4", check="5/5 pass each")
fact("T8b", "P38", "v1", "the agent reported {v} passing tests", "56", "65", check="56 pass")
fact("T8b", "P39", "v1", "the seeded crash was found in {v} seconds according to the report", "0.73", "4")
fact("T8b", "P41", "v1", "the backend choice was deferred to step {v}", "2", "3", check="step 2")
fact("T8b", "P42", "v1", "copying 800 GB at 500 MB/s was computed to take {v} minutes", "26.7", "16.7")
fact("T8b", "P42", "v1", "PostgreSQL {v} was confirmed as the current major version", "18", "17", check="PG18 current")
fact("T8b", "P46", "v1", "the LightGBM mean RMSE was {v}", "0.4742", "0.4777")
fact("T8b", "P46", "v1", "the Ridge RMSE standard deviation was {v}", "0.3923", "0.0058")
fact("b0v2", "P10", "v2", "the grader re-ran the Lean file {v}", "Check.lean", "Proof.lean")
fact("b0v2", "P12", "v2", "the rejected unbalanced post had {v} in debits against 999 in credits", "1000", "999", check="1000 D")
fact("b0v2", "P12", "v2", "the balancing trigger was named {v}", "transactions_balance", "entries_balance")
fact("b0v2", "P12", "v2", "the agent reported {v} passing tests", "10", "11", check="10 tests pass")
fact("b0v2", "P14", "v2", "cue 2 was measured at about {v} characters per second", "16", "18.2", check="16 cps")
fact("b0v2", "P25", "v2", "FalseVariant.lean was rejected by {v}", "rfl", "decide")
fact("b0v2", "P25", "v2", "the grader re-ran the Lean file {v}", "OddSum.lean", "SumOdd.lean")
fact("b0v2", "P30", "v2", "the test file contained {v} pytest cases", "17", "9", check="17 pytest cases")
fact("b0v2", "P31", "v2", "the report counted {v} Rust tests", "5", "3", check="5 Rust tests")
fact("b0v2", "P32", "v2", "the 20-second fuzz re-run executed {v} inputs with no failure", "22.5M", "24.9M")
fact("b0v2", "P32", "v2", "the table test had {v} cases", "32", "21", check="32 table cases")
fact("b0v2", "P33", "v2", "pnpm install failed because the store lock was refused by the {v}", "sandbox", "network")
fact("b0v2", "P35", "v2", "the offline cabal test re-run gave {v} examples with 0 failures", "14", "41", check="14 examples")
fact("b0v2", "P36", "v2", "test.log showed {v} of 31 Pkg.test tests passing", "31", "13", check="31/31")
fact("b0v2", "P36", "v2", "runtests.jl contained {v} @inferred checks", "10", "12", check="10 @inferred")
fact("b0v2", "P39", "v2", "the seeded crash was found in {v} seconds according to the report", "4", "0.73", check="4s per report")
fact("b0v2", "P40", "v1", "the scratch tree had 8 files, 4 directories and {v} symbolic links", "4", "2", check="4 links")
fact("b0v2", "P43", "v1", "{v} of 34 assertions passed via the MCP browser", "34", "33", check="34/34")
fact("b0v2", "P44", "v1", "{v} screenshots exist", "6", "3", aliases=["six"], check="Six screenshots")
fact("b0v2", "P45", "v1", "the agent's own pikepdf audit reported {v} PASS results", "29", "28", check="29 PASS")
fact("b0v2", "P48", "v1", "the maximum absolute difference for float64 input was {v}", "1.31e-7", "9.4e-8")
fact("b0v2", "P49", "v1", "the negative TWFE weight was {v}", "-0.133", "-0.233")
fact("b0v2", "P51", "v1", "{v} explain plans used IXSCAN", "5", "4", check="all 5 explain plans IXSCAN")
fact("b0v2", "P51", "v1", "the unread-count aggregation was checked on {v} rooms", "4", "5", check="4 rooms")
fact("b0v2", "P54", "v1", "the self-test of score_extraction.py passed {v} checks", "10", "12", check="10 checks passed")
fact("b0v2", "P55", "v1", "BM25 recall@3 was {v} out of 10", "9", "10", check="bm25 9/10")
fact("b0v2", "P56", "v1", "{v} of the 300 tickets were kept", "250", "240", check="250 kept of 300")
fact("b0v2", "P57", "v1", "the cage extrusion was {v} percent", "2", "3", check="cage extrusion 2%")
fact("b0v2", "P57", "v1", "the bake margin was {v} px", "16", "8", check="16 px bake margin")
fact("b0v2", "P58", "v1", "the Euler characteristic of the meshes was {v}", "2", "0", check="Euler 2")
fact("b0v2", "P58", "v1", "the larger STL volume was {v} mm3", "10334", "4916")
fact("b0v2", "P59", "v1", "the note names Houdini OCIO config version {v}", "3.0", "2.1", kind="str")
fact("b0v2", "P60", "v1", "the MP4 had {v} frames at 30 fps", "180", "150", check="180 frames")
fact("b0v2", "P61", "v1", "the halftone screen angle was {v} degrees", "22.5", "45", check="22.5 deg")
fact("b0v2", "P62", "v1", "the SVG fox was {v} mm wide", "62", "60", check="width 62mm")
fact("b0v2", "P64", "v1", "the recomputed chart compared 200000 with {v}", "43000", "34000")
fact("b0v2", "P65", "v1", "the HTML had {v} math spans", "2", "3", check="2 math spans")
fact("b0v2", "P66", "v1", "the page width was {v} pt", "441", "432", check="441x666 pt")
fact("b0v2", "P66", "v1", "the typst version on the host was {v}", "0.15.1", "0.14.1", kind="str")
fact("b0v2", "P70", "v1", "the argon2id memory parameter m was {v}", "65536", "32768", check="m=65536")
fact("b0v2", "P70", "v1", "the test file counted {v} cases", "30", "32", check="30 cases")
fact("b0v2", "P71", "v1", "the custom regex matched all {v} fake keys", "3", "2", check="all 3 fake keys")
fact("b0v2", "P71", "v1", "audit.json showed {v} critical minimist finding(s)", "1", "2", check="1 critical minimist")

PROMPT_HEAD = """Closed-book research task. Your working directory holds a frozen corpus of records from an earlier benchmark
campaign of AI coding and research agents. Use only these files (no network, no memory of the campaign):
- prompts/<id>.md: one benchmark prompt each (family, target agent, prompt text, rubric).
- grades/<batch>/<id>-<variant>.md: one grade record each. Batches T8a and T8b graded first runs (variant v1);
  batch b0v2 was graded later and covers v2 re-runs of some prompts and v1 runs of others.
  Results: pass, partial, fail, tool-absent.
- runs/<id>.md: per-session metrics of the runs of some prompts (agent type actually used, model, turns,
  tool calls, subagents spawned, total tokens, reported status).
A prompt without a grade record has no recorded grade; the corpus records nothing that its files do not state.

Claim: {claim}

Label the claim SUPPORTED (a record states it), REFUTED (a record contradicts it; put the correct value in
`value`) or NOT_IN_CORPUS (no record states or contradicts it). Cite the deciding record in `evidence`
(path and a quote). `rationale`: at most three sentences that name the deciding record."""


def load(name):
    with open(SRC / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_corpus(prompts, grades, runs):
    if CORPUS.exists():
        shutil.rmtree(CORPUS)
    docs = {}
    for p in prompts:
        docs[f"prompts/{p['id']}.md"] = (
            f"# Prompt {p['id']}\n\nfamily: {p['family']}\ntarget agent: {p['target_agent']}\n"
            f"expected skills: {p['expected_skills']}\ncost class: {p['cost_class']}\n\n"
            f"prompt: {p['prompt']}\n\nrubric: {p['check']}\n\nnotes: {p['notes']}\n")
    for g in grades:
        kind = "v2 re-run" if g["variant"] == "v2" else "v1 (first run)"
        docs[f"grades/{g['batch']}/{g['id']}-{g['variant']}.md"] = (
            f"# Grade record: {g['id']}, variant {g['variant']}, batch {g['batch']}\n\nbatch: {g['batch']}\n"
            f"prompt: {g['id']}\nvariant: {kind}\ncheck_result: {g['check_result']}\n"
            f"grader evidence: {g['why']}\n")
    by_id = {}
    for r in runs:
        by_id.setdefault(r["prompt_id"], []).append(r)
    for pid, rows in by_id.items():
        lines = [f"# Run record: {pid} (agents-baseline campaign)", "", f"sessions recorded: {len(rows)}", ""]
        for i, r in enumerate(rows, 1):
            role = "root" if r["is_root"] == "1" else "child (spawned by the root)"
            lines.append(f"- session {i}: role {role}, agent type {r['agent_type']}, model {r['model']}, "
                         f"turns {r['turns']}, tool calls {r['tool_calls']}, subagents spawned {r['spawn_count']}, "
                         f"total tokens {r['tokens_total']}, reported status {r['final_status']}")
        docs[f"runs/{pid}.md"] = "\n".join(lines) + "\n"
    for path, text in docs.items():
        f = CORPUS / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return docs


def subject(pid, var, batch, use_desc):
    x = DESC[pid] if use_desc else f"prompt {pid}"
    if var == "v2":
        return f"the v2 re-run of {x}"
    if batch == "b0v2":
        return f"the first (v1) run of {x}"
    return f"the run of {x}"


def main():
    prompts, grades, runs = load("prompts.csv"), load("grades.csv"), load("runs.csv")
    assert set(DESC) == {p["id"] for p in prompts}
    assert len(set(DESC.values())) == len(DESC)
    docs = build_corpus(prompts, grades, runs)
    gmap = {(g["batch"], g["id"], g["variant"]): g for g in grades}
    rng = np.random.default_rng(SEED_GEN)
    cands = []

    def add(claim_fn, label, key_value, false_value, kind, aliases, decisive, reason, pid, family):
        use_desc = bool(rng.random() < 0.4)
        cands.append(dict(claim=claim_fn(use_desc), label=label, value=key_value, false_value=false_value,
                          kind=kind, aliases=aliases, decisive=decisive, reason=reason, prompt_id=pid,
                          family=family, ref="descriptor" if use_desc else "id"))

    # A: grade-label claims, one per grade record
    for g in grades:
        t = g["check_result"]
        alt = {"pass": ["partial", "fail"], "partial": ["pass", "fail"], "tool-absent": ["pass", "partial"]}[t]
        sup = bool(rng.random() < 0.5)
        v = t if sup else alt[int(rng.integers(len(alt)))]
        path = f"grades/{g['batch']}/{g['id']}-{g['variant']}.md"
        add(lambda d, g=g, v=v: f"In the {g['batch']} grading, {subject(g['id'], g['variant'], g['batch'], d)} "
                                f"received the result \"{v}\".",
            "SUPPORTED" if sup else "REFUTED", t, None if sup else v, "str", [], path,
            f"{path} records check_result: {t}", g["id"], "A-grade-label")
    # B: evidence claims hand-extracted from grader evidence lines
    for f in F:
        g = gmap[(f["batch"], f["id"], f["variant"])]
        assert f["check"] in g["why"], (f, g["why"])
        assert f["true"] != f["false"]
        sup = bool(rng.random() < 0.5)
        v = f["true"] if sup else f["false"]
        path = f"grades/{f['batch']}/{f['id']}-{f['variant']}.md"
        add(lambda d, f=f, v=v: f"In the {f['batch']} grading of {subject(f['id'], f['variant'], f['batch'], d)}, "
                                + f["body"].format(v=v) + ".",
            "SUPPORTED" if sup else "REFUTED", f["true"], None if sup else f["false"], f["kind"], f["aliases"], path,
            f"{path} grader evidence contains: {f['check']}", f["id"], "B-grade-evidence")
    # C: run-metric claims, one per prompt with run records
    by_id = {}
    for r in runs:
        by_id.setdefault(r["prompt_id"], []).append(r)
    target = {p["id"]: p["target_agent"] for p in prompts}
    agent_pool = sorted({r["agent_type"] for r in runs})
    for pid in sorted(by_id, key=lambda s: int(s[1:])):
        rows = by_id[pid]
        path = f"runs/{pid}.md"
        sup = bool(rng.random() < 0.5)
        if sum(r["is_root"] == "1" for r in rows) > 1:
            t, fv = str(len(rows)), str(len(rows) - 2)
            body, kind = "the run records list {v} sessions", "num"
        else:
            root = next(r for r in rows if r["is_root"] == "1")
            field = ["agent_type", "model", "turns", "tool_calls", "tokens_total"][int(rng.integers(5))]
            if pid == "P29":
                field = "spawn_count"
            t = root[field]
            if field == "agent_type":
                tg = target[pid]
                if re.fullmatch(r"[a-z-]+", tg) and tg != t:
                    fv = tg
                else:
                    others = [a for a in agent_pool if a != t]
                    fv = others[int(rng.integers(len(others)))]
                body, kind = "the root session was run by the agent type {v}", "str"
            elif field == "model":
                fv = "claude-opus-5-5" if t == "claude-sonnet-5-5" else "claude-sonnet-5-5"
                body, kind = "the root session ran on the model {v}", "str"
            elif field == "tokens_total":
                fv = str(int(round(int(t) * [0.8, 1.25][int(rng.integers(2))])))
                body, kind = "the root session used {v} tokens in total", "num"
            else:
                d = [-3, -2, 2, 3, 5][int(rng.integers(5))]
                fv = str(int(t) + d if int(t) + d >= 0 else int(t) + 3)
                body = {"turns": "the root session took {v} turns", "tool_calls": "the root session made {v} tool calls",
                        "spawn_count": "the root session spawned {v} subagents"}[field]
                kind = "num"
        v = t if sup else fv
        add(lambda d, pid=pid, body=body, v=v: "According to the run records of the agents-baseline campaign, for "
            + (DESC[pid] if d else f"prompt {pid}") + ", " + body.format(v=v) + ".",
            "SUPPORTED" if sup else "REFUTED", t, None if sup else fv, kind, [], path,
            f"{path} states {body.format(v=t)}", pid, "C-run-metric")
    # D1: outcome claims about prompts without any grade record (and without run records)
    graded = {g["id"] for g in grades}
    for p in prompts:
        pid = p["id"]
        if pid in graded or pid in by_id:
            continue
        v = VOCAB[int(rng.integers(3))]
        add(lambda d, pid=pid, v=v: f"The run of {DESC[pid] if d else 'prompt ' + pid} was graded \"{v}\".",
            "NOT_IN_CORPUS", None, None, "none", [], None,
            f"no grade record and no run record exists for {pid}; only prompts/{pid}.md mentions it", pid, "D-ungraded")
    # D2: wall-time claims (wall time is not part of any record)
    for pid in sorted(by_id, key=lambda s: int(s[1:])):
        root = next(r for r in by_id[pid] if r["is_root"] == "1")
        if rng.random() < 0.45:
            v = str(int(round(float(root["wall_s"]))))
            add(lambda d, pid=pid, v=v: "According to the run records of the agents-baseline campaign, the root "
                f"session for {DESC[pid] if d else 'prompt ' + pid} lasted {v} seconds of wall time.",
                "NOT_IN_CORPUS", None, None, "none", [], None,
                f"runs/{pid}.md records no wall time or timestamps; no record states a duration for this session",
                pid, "D-unrecorded-field")

    order = rng.permutation(len(cands))
    cands = [cands[i] for i in order]
    dev = []
    for want in ("SUPPORTED", "REFUTED", "NOT_IN_CORPUS"):
        j = next(i for i, c in enumerate(cands) if c["label"] == want)
        dev.append(cands.pop(j))
    seg_paths = sorted(docs)
    seg_rng = np.random.default_rng(SEED_ITEMS)
    manifest, keys = [], []
    items = [(f"RS-DEV{i + 1}", True, c) for i, c in enumerate(dev)] + \
            [(f"RS-{i + 1:04d}", False, c) for i, c in enumerate(cands)]
    for iid, is_dev, c in items:
        perm = seg_rng.permutation(len(seg_paths))
        segs = [{"id": f"s{k:03d}", "path": seg_paths[k]} for k in perm]
        dec = None if c["decisive"] is None else next(i for i, s in enumerate(segs) if s["path"] == c["decisive"])
        manifest.append({"id": iid, "class": "RS", "dev": is_dev, "answer_kind": "discrete",
                         "prompt": PROMPT_HEAD.format(claim=c["claim"]), "segments": segs, "decisive_segment": dec,
                         "fixture": "fixtures/corpus", "public_check": None, "allowed_tools": ALLOWED_TOOLS})
        excerpt = docs[c["decisive"]] if c["decisive"] else None
        if excerpt and c["ref"] == "descriptor":
            excerpt = docs[f"prompts/{c['prompt_id']}.md"].split("\n\nprompt:")[0] + "\n\n" + excerpt
        keys.append({"id": iid, "claim": c["claim"], "label": c["label"], "value": c["value"],
                     "value_kind": c["kind"], "aliases": c["aliases"], "claimed_false_value": c["false_value"],
                     "decisive_path": c["decisive"], "reference_excerpt": excerpt, "reason": c["reason"],
                     "source_prompt": c["prompt_id"], "family": c["family"], "ref_style": c["ref"]})
    (CLS_DIR / "manifest.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in manifest))
    (CLS_DIR / "oracle").mkdir(exist_ok=True)
    (CLS_DIR / "oracle" / "keys.jsonl").write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in keys))
    # self-test answers for the dev items: reference (key) and seeded wrong answers
    st = CLS_DIR / "selftest"
    st.mkdir(exist_ok=True)
    for iid, _, c in items[:3]:
        k = next(x for x in keys if x["id"] == iid)
        ref_val = k["value"] if k["label"] == "REFUTED" else ""
        ref = {"answer": {"label": k["label"], "value": ref_val,
                          "rationale": f"Deciding record: {k['decisive_path'] or 'none'}. {k['reason']}."},
               "evidence": [{"kind": "file_line", "ref": k["decisive_path"] or "-", "detail": "deciding record"}],
               "confidence": 0.8}
        wrong_label = {"SUPPORTED": "REFUTED", "REFUTED": "SUPPORTED", "NOT_IN_CORPUS": "SUPPORTED"}[k["label"]]
        wrong = {"answer": {"label": wrong_label, "value": "", "rationale": "The record says otherwise."},
                 "evidence": [], "confidence": 0.6}
        (st / f"{iid}.ref.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1) + "\n")
        (st / f"{iid}.wrong.json").write_text(json.dumps(wrong, ensure_ascii=False, indent=1) + "\n")
        if k["label"] == "REFUTED":  # right label, wrong correction value
            wv = dict(ref, answer=dict(ref["answer"], value=k["claimed_false_value"]))
            (st / f"{iid}.wrongvalue.json").write_text(json.dumps(wv, ensure_ascii=False, indent=1) + "\n")
    from collections import Counter
    print("items", len(manifest), "dev", len(dev), "labels", Counter(k["label"] for k in keys[3:]),
          "families", Counter(k["family"] for k in keys[3:]), "corpus docs", len(docs), "gen seed", SEED_GEN)


if __name__ == "__main__":
    main()
