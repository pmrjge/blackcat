# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""FAKE ES oracle for the harness tests: e = |ln(estimate / 100)|; a missing or non-positive estimate prints the
string "inf" (as the real items/ES/oracle.py does)."""

import argparse
import json
import math
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--item", required=True)
ap.add_argument("--answer", required=True)
ap.add_argument("--workdir")
a = ap.parse_args()
v = json.loads(Path(a.answer).read_text()).get("answer")
ok = isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v > 0
print(json.dumps({"item": a.item, "score": abs(math.log(v / 100)) if ok else "inf", "detail": {}}))
