"""The Losses page's dimension pickers match the loss tools' allow-lists."""

import json
import re
from pathlib import Path

from linecopilot.tools.losses import BREAKDOWN_DIMS, PARETO_DIMS, REPEAT_KEYS

PAGE = Path(__file__).resolve().parents[2] / "web" / "src" / "pages" / "Losses.tsx"


def web_const(name: str) -> dict[str, tuple[str, ...]]:
    m = re.search(
        rf"const {name}: Record<string, string\[\]> = \{{(.*?)\}};", PAGE.read_text(), re.S
    )
    assert m, f"{name} not found in {PAGE.name}"
    body = re.sub(r"(\w+):", r'"\1":', m.group(1)).rstrip().rstrip(",")
    return {k: tuple(v) for k, v in json.loads("{" + body + "}").items()}


def test_losses_page_dimensions_match_backend():
    assert web_const("PARETO_BY") == PARETO_DIMS
    assert web_const("BREAK_DIMS") == BREAKDOWN_DIMS
    assert web_const("REPEAT_KEYS") == REPEAT_KEYS
