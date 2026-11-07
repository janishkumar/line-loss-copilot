"""Print PIADE OEE per machine over its full coverage, from the dbt marts.

Usage: PYTHONPATH=src uv run python scripts/piade_oee_summary.py
"""

from __future__ import annotations

import pandas as pd

from linecopilot.config import get_settings
from linecopilot.db import connect
from linecopilot.reports.piade_summary import piade_machine_summary


def main() -> None:
    with connect(get_settings().database_url) as conn:
        df = piade_machine_summary(conn)
    pd.set_option("display.width", 200)
    print(df.T.to_string(float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
