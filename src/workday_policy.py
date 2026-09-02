# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Hard bounds and deterministic classification for simulated workdays."""

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List


EMAIL_REPLY_DEPTH_KEY = "_chimera_reply_depth"
_MEMBER_MENTION_RE = re.compile(r"(?<![\w-])@([A-Za-z0-9][A-Za-z0-9-]*)")
_EMAIL_ONLY_RE = re.compile(
    r"^\s*(?:send|draft|write|reply(?:\s+to)?|forward)\s+(?:an?\s+)?email\b"
    r"|^\s*email\b"
    r"|^\s*contact\b.*\b(?:by|via|through)\s+email\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_COMPOUND_RE = re.compile(
    r"\b(?:and|then)\s+(?:begin|build|configure|create|document|draft|"
    r"finalize|implement|install|prepare|review|run|test|update|validate|"
    r"write)\b",
    re.IGNORECASE,
)


def parse_clock_time(value: str) -> datetime:
    """Parse an HH:MM or HH:MM:SS clock value."""

    if not isinstance(value, str):
        raise ValueError("Clock time must be a string.")
    for time_format in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), time_format)
        except ValueError:
            continue
    raise ValueError(f"Invalid clock time {value!r}; use HH:MM or HH:MM:SS.")


def email_reply_depth(message: Dict[str, Any]) -> int:
    """Return trusted reply depth, treating malformed metadata as an origin."""

    depth = message.get(EMAIL_REPLY_DEPTH_KEY, 0)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        return 0
    return depth


def reply_metadata(message: Dict[str, Any]) -> Dict[str, int]:
    """Metadata for a reply to *message*."""

    return {EMAIL_REPLY_DEPTH_KEY: email_reply_depth(message) + 1}


def reply_allowed(message: Dict[str, Any], max_reply_depth: int) -> bool:
    """Whether another reply may be generated for this conversation."""

    return email_reply_depth(message) < max_reply_depth


def bounded_pending_tasks(
    tasks: Iterable[Dict[str, Any]],
    current_time: datetime,
    workday_end: datetime,
) -> List[Dict[str, Any]]:
    """Keep only future replan tasks strictly inside working hours."""

    return [
        task
        for task in tasks
        if current_time < parse_clock_time(task["Time"]) < workday_end
    ]


def mentioned_member_ids(activity: str) -> List[str]:
    """Return exact ``@member-id`` mentions in first-seen order."""

    if not isinstance(activity, str):
        return []
    return list(dict.fromkeys(_MEMBER_MENTION_RE.findall(activity)))


def is_email_only_activity(activity: str) -> bool:
    """Classify a schedule entry that only represents sending an email.

    A bare ``@id`` is deliberately not sufficient: entries such as "create the
    report and email @data-1" must execute the work before sending a grounded
    hand-off email.
    """

    if not isinstance(activity, str) or not mentioned_member_ids(activity):
        return False
    return bool(_EMAIL_ONLY_RE.search(activity)) and not bool(
        _SUBSTANTIVE_COMPOUND_RE.search(activity)
    )


def activity_validation_errors(
    activity: str, member_id: str, known_member_ids: Iterable[str]
) -> List[str]:
    """Validate deterministic colleague addressing in one schedule entry."""

    errors: List[str] = []
    if "@PEOPLE" in activity.upper():
        errors.append("uses the forbidden @PEOPLE placeholder")
    known = set(known_member_ids)
    mentions = mentioned_member_ids(activity)
    if member_id in mentions:
        errors.append(f"mentions the employee's own id @{member_id}")
    unknown = sorted(set(mentions) - known)
    if unknown:
        errors.append(
            "mentions unknown member id(s): "
            + ", ".join(f"@{value}" for value in unknown)
        )
    return errors
