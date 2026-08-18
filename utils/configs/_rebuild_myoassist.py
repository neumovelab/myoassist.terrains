"""One-shot rebuild for both myoassist terrains.

After editing either the base JSON config or `terrain_style.xml`, run this
to regenerate both `terrain/myoassist_base.xml` and `terrain/myoassist_base_tiled3x3.xml`
so whichever one is currently active picks up the change. Otherwise it's easy
to rebuild only the small base while the visualizer is loading the stale 9x9.

Usage (from anywhere; paths resolve relative to this script):
    python utils/configs/_rebuild_myoassist.py
"""

import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
base_json = here / "myoassist_base.json"
tiled_json = here / "myoassist_tiled.json"
make_tiled = here / "_make_tiled.py"


def run(cmd):
    print(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


# 1) Build the base. Picks up edits to the base JSON, including its
#    palette: {"uniform": [...]} entry, which is where the uniform colour lives.
run([sys.executable, "-m", "myoassist_terrains", "build", str(base_json)])

# 2) Regenerate the tiled JSON from the (possibly edited) base JSON. Carries
#    over `texture`, `palette`, etc. via _make_tiled.py.
run([sys.executable, str(make_tiled), str(base_json), str(tiled_json)])

# 3) Build the tiled terrain.
run([sys.executable, "-m", "myoassist_terrains", "build", str(tiled_json)])

print("\nDone. Active terrain unchanged; restart the visualizer to see edits.")
