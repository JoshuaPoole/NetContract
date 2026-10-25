"""Run behavioural checks against the shipped JavaScript without external services."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_canonical_review_ui_behaviour():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the UI script checks")
    script = Path(__file__).with_name("canonical_review_dom.cjs")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr

