"""Canonical action arguments.

Every action's arguments are parsed into a strict model (unknown fields, including any identity
field, are refused), then reduced to one canonical dict. The hash of that dict, together with the
action and the acting identity, is what a confirmation code is bound to, so a whitespace-only or
ordering-only edit between preview and propose still matches and any other edit does not."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from linecopilot.actions.identity import ActionContext
from linecopilot.tools.registry import format_errors

Role = Literal["operator", "shift_supervisor", "planner", "quality_lead", "plant_manager"]


class InvalidArgs(ValueError):
    """Arguments refused; the message is one line."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _evidence(min_length: int):
    return Field(min_length=min_length, max_length=50)


class WorkOrderArgs(_Base):
    asset_id: str = Field(min_length=1, max_length=40)
    failure_mode: str = Field(min_length=1, max_length=140)
    priority: Literal["low", "medium", "high", "critical"]
    description: str = Field(min_length=1, max_length=2000)
    evidence_event_ids: list[int] = _evidence(1)


class QualityHoldArgs(_Base):
    asset_id: str = Field(min_length=1, max_length=40)
    product: str | None = Field(default=None, max_length=140)
    window_start: datetime
    window_end: datetime
    reason: str = Field(min_length=1, max_length=2000)
    evidence_event_ids: list[int] = _evidence(1)

    @field_validator("window_start", "window_end")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("must include a timezone")
        return v

    @model_validator(mode="after")
    def _ordered(self):
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self

    @field_serializer("window_start", "window_end")
    def _utc(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat()


class FollowUpArgs(_Base):
    assignee_role: Role
    due_date: date
    description: str = Field(min_length=1, max_length=2000)
    evidence_event_ids: list[int] = _evidence(0)


ACTION_ARGS: dict[str, type[_Base]] = {
    "work_order": WorkOrderArgs,
    "quality_hold": QualityHoldArgs,
    "follow_up": FollowUpArgs,
}


def parse(action: str, raw: dict) -> _Base:
    model = ACTION_ARGS.get(action)
    if model is None:
        raise InvalidArgs(f"unknown action: {action}")
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        raise InvalidArgs(format_errors(e.errors())) from e


def canonical(action: str, model: _Base) -> dict[str, Any]:
    out = model.model_dump(mode="json")
    out["evidence_event_ids"] = sorted(set(out["evidence_event_ids"]))
    return out


def payload_sha256(action: str, ctx: ActionContext, canon: dict) -> str:
    """sha256 of the canonical JSON of action, principal, on_behalf_of and args (sorted keys).
    The channel is deliberately not bound: a preview in one front end may be confirmed in the
    same human's name through the same principal only."""
    body = json.dumps(
        {
            "action": action,
            "principal": ctx.principal,
            "on_behalf_of": ctx.on_behalf_of,
            "args": canon,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
