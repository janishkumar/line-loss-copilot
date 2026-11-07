"""Generate the synthetic orders, BOMs and stock and write them to the database.

python -m linecopilot.synth [--seed 7]"""

from __future__ import annotations

import argparse

import psycopg

from linecopilot.config import get_settings
from linecopilot.synth.anchors import load_anchors
from linecopilot.synth.generate import DEFAULT_SEED, content_hash, generate, load_factor, write


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    with psycopg.connect(get_settings().database_url) as conn:
        anchors = load_anchors(conn)
        data = generate(anchors, args.seed)
        gid = write(conn, data, anchors, args.seed)
    print(f"generation {gid} seed {args.seed} sha256 {content_hash(data)}")
    print(f"load factor {load_factor(data, anchors):.3f}  orders {len(data.customer_order)}")
    for m in sorted(anchors.rates):
        print(
            f"  {m}: {anchors.rates[m]:.0f}/h, availability {anchors.availability[m]:.4f} "
            f"[{anchors.sources['availability_window'][m]}]"
        )
    print(
        f"changeover same-family {anchors.changeover_same_family_min} min, "
        f"cross-family {anchors.changeover_cross_family_min} min"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
