# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write sha256 manifests for the frozen inputs.

  uv run --script tools/manifest.py            # writes inputs/MANIFEST.sha256 and inputs/run_tree_manifest.tsv
  uv run --script tools/manifest.py --check    # verifies inputs/MANIFEST.sha256, exit 1 on any mismatch

MANIFEST.sha256 : `sha256sum` format over every file under inputs/ (except the manifest itself).
run_tree_manifest.tsv : path, bytes, sha256 of every file under ../run/ (the agents' run outputs,
                        1.3 GB, NOT copied; hashed so later edits to run/ are detectable).
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SB = os.path.dirname(HERE)
INP = os.path.join(SB, "inputs")
RUN = os.path.join(os.path.dirname(SB), "run")
MAN = os.path.join(INP, "MANIFEST.sha256")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            yield os.path.join(d, f)


def main():
    if "--check" in sys.argv:
        bad = 0
        for line in open(MAN, encoding="utf-8"):
            h, rel = line.rstrip("\n").split("  ", 1)
            p = os.path.join(INP, rel)
            if not os.path.exists(p) or sha(p) != h:
                print("MISMATCH", rel)
                bad += 1
        print(f"checked {sum(1 for _ in open(MAN))} files, {bad} mismatches")
        sys.exit(1 if bad else 0)
    rows = []
    for p in walk(INP):
        rel = os.path.relpath(p, INP)
        if rel in ("MANIFEST.sha256",):
            continue
        rows.append(f"{sha(p)}  {rel}")
    with open(MAN, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    n = 0
    with open(os.path.join(INP, "run_tree_manifest.tsv"), "w", encoding="utf-8") as fh:
        fh.write("path\tbytes\tsha256\n")
        for p in walk(RUN):
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            fh.write(f"{os.path.relpath(p, os.path.dirname(RUN))}\t{os.path.getsize(p)}\t{sha(p)}\n")
            n += 1
    # re-hash so the manifest covers run_tree_manifest.tsv too
    rows = [f"{sha(p)}  {os.path.relpath(p, INP)}" for p in walk(INP) if os.path.relpath(p, INP) != "MANIFEST.sha256"]
    with open(MAN, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    print(f"inputs: {len(rows)} files hashed; run tree: {n} files hashed")


if __name__ == "__main__":
    main()
