"""Who may propose and approve each action, loaded from config/policy.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ACTIONS = ("work_order", "quality_hold", "follow_up")
ROLES = ("operator", "shift_supervisor", "planner", "quality_lead", "plant_manager")
PRIORITIES = ("low", "medium", "high", "critical")

_SECTIONS = {"confirmation", "propose", "approve", "priority", "evidence", "review"}
_REQUIRED = _SECTIONS - {"review"}
REVIEW_DEFAULT = ("quality_lead", "shift_supervisor", "plant_manager")


@dataclass(frozen=True)
class Policy:
    ttl_minutes: int
    propose: dict[str, tuple[str, ...]]
    approve: dict[str, tuple[str, ...]]
    priority: dict[str, tuple[int, int]]
    max_events: int
    review_vision: tuple[str, ...] = REVIEW_DEFAULT

    def may_review_image(self, role: str) -> bool:
        return role in self.review_vision

    def may_propose(self, role: str, action: str) -> bool:
        return action in self.propose.get(role, ())

    def may_approve(self, role: str, action: str) -> bool:
        return role in self.approve.get(action, ())

    def priority_floor(self, priority: str) -> tuple[int, int] | None:
        """(min_stop_s, min_events) the evidence should reach, or None if no floor."""
        return self.priority.get(priority)


def _only(d: dict, allowed, where: str) -> None:
    extra = set(d) - set(allowed)
    if extra:
        raise ValueError(f"unknown key(s) in {where}: {sorted(extra)}")


def _names(values, allowed, where: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{where} must be a list")
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError(f"unknown name(s) in {where}: {bad}")
    return tuple(values)


def load_policy(path: str | Path) -> Policy:
    data = tomllib.loads(Path(path).read_text())
    _only(data, _SECTIONS, "policy")
    missing = _REQUIRED - set(data)
    if missing:
        raise ValueError(f"missing section(s): {sorted(missing)}")

    conf = data["confirmation"]
    _only(conf, {"ttl_minutes"}, "[confirmation]")
    ttl = conf["ttl_minutes"]
    if not isinstance(ttl, int) or ttl <= 0:
        raise ValueError("confirmation.ttl_minutes must be a positive integer")

    _only(data["propose"], ROLES, "[propose]")
    propose = {r: _names(v, ACTIONS, f"propose.{r}") for r, v in data["propose"].items()}
    _only(data["approve"], ACTIONS, "[approve]")
    approve = {a: _names(v, ROLES, f"approve.{a}") for a, v in data["approve"].items()}

    _only(data["priority"], PRIORITIES, "[priority]")
    priority: dict[str, tuple[int, int]] = {}
    for name, floor in data["priority"].items():
        _only(floor, {"min_stop_s", "min_events"}, f"priority.{name}")
        if set(floor) != {"min_stop_s", "min_events"}:
            raise ValueError(f"priority.{name} needs min_stop_s and min_events")
        if not all(
            isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in floor.values()
        ):
            raise ValueError(f"priority.{name} values must be positive integers")
        priority[name] = (floor["min_stop_s"], floor["min_events"])

    ev = data["evidence"]
    _only(ev, {"max_events"}, "[evidence]")
    if not isinstance(ev["max_events"], int) or ev["max_events"] <= 0:
        raise ValueError("evidence.max_events must be a positive integer")

    review = data.get("review", {})
    _only(review, {"vision"}, "[review]")
    review_vision = (
        _names(review["vision"], ROLES, "review.vision") if "vision" in review else REVIEW_DEFAULT
    )

    return Policy(ttl, propose, approve, priority, ev["max_events"], review_vision)
