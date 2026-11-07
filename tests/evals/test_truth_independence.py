"""Ground truth must not share code with the layer it checks."""

import ast
import json
import subprocess
import sys
from pathlib import Path

TRUTH = Path(__file__).resolve().parents[2] / "evals" / "truth.py"
FORBIDDEN = ("linecopilot.tools", "linecopilot.api", "linecopilot.chat")


def imported_modules(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: flagged, truth.py imports absolute only
                mods.add("." * node.level + (node.module or ""))
            elif node.module:
                mods.add(node.module)
                mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def test_truth_does_not_import_tool_layer():
    mods = imported_modules(TRUTH)
    assert mods, "parser found no imports"
    bad = [m for m in mods if m == "linecopilot" or m.startswith((*FORBIDDEN, "."))]
    assert not bad, bad


def test_parser_sees_forbidden_import(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("from linecopilot.tools.losses import loss_pareto\nimport linecopilot.chat\n")
    mods = imported_modules(p)
    assert "linecopilot.tools.losses" in mods and "linecopilot.chat" in mods


def test_parser_flags_relative_imports(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("from . import questions\nfrom ..tools import losses\n")
    assert {".", "..tools"} <= imported_modules(p)


def test_importing_truth_loads_no_tool_layer():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import json, sys; import evals.truth; "
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('linecopilot'))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={"PYTHONPATH": f"{root}:{root / 'src'}", "PATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(out.stdout)
    assert not [m for m in loaded if m.startswith(FORBIDDEN)], loaded
