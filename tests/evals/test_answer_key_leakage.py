"""No answer key in what the model sees: the dataset's own conclusions stay out of prompts,
tool descriptions and question text."""

import json
import re

from evals.before_after import PROMPT
from evals.questions import build_questions
from linecopilot.chat.prompt import SYSTEM_PROMPT
from linecopilot.mcp_server.server import INSTRUCTIONS
from linecopilot.prompting import BASE_INSTRUCTIONS
from linecopilot.tools.registry import TOOLS

# The improvement programme behind the brick data and words from the dataset record's title.
BANNED = re.compile(r"\blean\b|six\s*sigma|DMAIC|kaizen|heavy\s*clay", re.IGNORECASE)
LSS = re.compile(r"LSS")  # case-sensitive: the file-name suffix and acronym


def model_visible_text() -> dict[str, str]:
    out = {
        "SYSTEM_PROMPT": SYSTEM_PROMPT,
        "BASE_INSTRUCTIONS": BASE_INSTRUCTIONS,
        "MCP INSTRUCTIONS": INSTRUCTIONS,
        "before_after.PROMPT": PROMPT,
    }
    for name, spec in TOOLS.items():
        out[f"tool {name}"] = spec.description
        out[f"schema {name}"] = json.dumps(spec.args_model.model_json_schema())
    for q in build_questions():
        out[q.id] = q.text
    return out


def test_no_published_conclusions_in_prompts():
    hits = {k: BANNED.findall(v) + LSS.findall(v) for k, v in model_visible_text().items()}
    assert not {k: v for k, v in hits.items() if v}


def test_banned_pattern_catches_the_words():
    for s in ("Lean Six Sigma", "DMAIC phase", "heavy clay"):
        assert BANNED.search(s)
    assert LSS.search("OEEdataset_afterLSS.csv")
    assert not BANNED.search("clean the boolean")
