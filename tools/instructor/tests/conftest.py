"""The scripts in ../bin and the helpers here are imported by module name."""
import sys
from pathlib import Path

for _d in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[1] / "bin"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
