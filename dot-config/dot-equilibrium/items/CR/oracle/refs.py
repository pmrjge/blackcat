"""Reference material for selftest and proof (harness-only; never shown to an arm)."""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.dirname(HERE)


def items():
    with open(os.path.join(HERE, "items.json")) as f:
        return json.load(f)


def seeded_workdir(item_id, dest):
    shutil.copytree(os.path.join(POOL, "fixtures", item_id), dest)
    return dest


def reference_workdir(item_id, dest):
    """Seeded fixture with every module restored to its reference (the fixed code)."""
    seeded_workdir(item_id, dest)
    for mod in items()[item_id]["files"]:
        shutil.copyfile(os.path.join(HERE, "bases", mod + ".py"), os.path.join(dest, mod + ".py"))
    return dest


def reference_findings(item_id):
    return [{"file": b["file"], "line": b["line"], "claim": b["claim"]} for b in items()[item_id]["bugs"]]


def write_answer(path, findings):
    with open(path, "w") as f:
        json.dump({"answer": findings, "evidence": [], "confidence": 1.0}, f)
