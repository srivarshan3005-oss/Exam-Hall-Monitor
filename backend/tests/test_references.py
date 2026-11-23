"""Frontend pages/links, API calls, model attributes and router registration must all resolve (scripts/check_references.py)."""
import subprocess, sys
from pathlib import Path


def test_cross_references_resolve():
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_references.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
