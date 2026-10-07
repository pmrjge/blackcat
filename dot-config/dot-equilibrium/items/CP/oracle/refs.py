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
    """Fresh copy of the seeded fixture."""
    shutil.copytree(os.path.join(POOL, "fixtures", item_id), dest)
    return dest


def reference_workdir(item_id, dest):
    """Seeded fixture with the module restored to the reference fix (the base module)."""
    seeded_workdir(item_id, dest)
    mod = items()[item_id]["module"]
    shutil.copyfile(os.path.join(HERE, "bases", mod + ".py"), os.path.join(dest, mod + ".py"))
    return dest


def answer_json(path, text="reference fix"):
    with open(path, "w") as f:
        json.dump({"answer": text, "evidence": [], "confidence": 1.0}, f)
