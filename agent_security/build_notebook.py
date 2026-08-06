"""Generate the Kaggle submission notebook from attack.py (single source of truth).

The competition's hosted evaluator loads and runs ``/kaggle/working/attack.py``
itself, so the notebook only needs to *write* that file.  Writing a file needs
no internet, so this works under the code-competition "internet disabled" rule.

Usage:  python agent_security/build_notebook.py
Output: agent_security/kaggle_submission.ipynb
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTACK_SRC = (HERE / "attack.py").read_text(encoding="utf-8")
OUT = HERE / "kaggle_submission.ipynb"


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def md_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


INTRO = """\
# AI Agent Security — Multi-Step Tool Attacks — Submission

This notebook writes `attack.py` to `/kaggle/working/`. The competition's hosted
evaluator loads that file and runs `AttackAlgorithm.run(env, config)` against each
target model (GPT-OSS-20b, Gemma) behind the public and private guardrails, then
produces `submission.csv`.

**Settings for the scored commit:** GPU on, Internet **off**. Writing the file
needs no network. The self-check cell is best-effort and is skipped if the SDK is
not importable at notebook-run time (it is always available in the evaluator).
"""

WRITE_CELL = "%%writefile /kaggle/working/attack.py\n" + ATTACK_SRC

SELFCHECK = """\
# Best-effort self-check (never fails the commit). The evaluator has the SDK;
# this cell just confirms the file parses and exposes AttackAlgorithm when the
# SDK happens to be importable in the notebook kernel too.
import importlib.util
import sys

path = "/kaggle/working/attack.py"
try:
    with open(path) as fh:
        assert "class AttackAlgorithm" in fh.read()
    spec = importlib.util.spec_from_file_location("submitted_attack", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # requires aicomp_sdk; fine to fail offline
    from aicomp_sdk.attacks import AttackAlgorithmBase
    assert issubclass(mod.AttackAlgorithm, AttackAlgorithmBase)
    inst = mod.AttackAlgorithm({})
    print("OK: attack.py written and AttackAlgorithm validated.")
except ModuleNotFoundError as e:
    print(f"attack.py written. SDK not importable here ({e}); evaluator will load it.")
except Exception as e:
    print(f"attack.py written. Self-check skipped: {type(e).__name__}: {e}")
"""

notebook = {
    "cells": [md_cell(INTRO), code_cell(WRITE_CELL), code_cell(SELFCHECK)],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes) embedding attack.py ({len(ATTACK_SRC):,} chars)")
