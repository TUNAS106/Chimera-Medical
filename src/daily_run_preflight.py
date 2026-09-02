# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# SPDX-License-Identifier: MIT
"""Validate one selected simulated day before any capture is opened."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import config
from workday_policy import (
    activity_validation_errors,
    is_email_only_activity,
    parse_clock_time,
)


_MEETING_RE = re.compile(
    r"^\s*(?:attend|hold|join|meet)\b"
    r"|^\s*conduct\b.*\b(?:meeting|session|call)\b"
    r"|^\s*(?:send|draft|write|email|check)\b.*\b"
    r"(?:schedule|request|propose|confirm)\b.*\bmeeting\b",
    re.IGNORECASE,
)


def validate_day(week: int, date: str) -> tuple[int, int]:
    profile_dir = Path(config.profile_output_dir)
    member_ids = {
        path.stem for path in profile_dir.glob("*.jsonc") if path.is_file()
    }
    if not member_ids:
        raise ValueError("No employee profiles were found.")
    start = parse_clock_time(config.workday_start)
    end = parse_clock_time(config.workday_end)
    total_tasks = 0
    artifact_members = 0
    for member_id in sorted(member_ids):
        path = (
            Path(config.init_schedule_dir)
            / f"week_{week}"
            / f"{member_id}_week_{week}_{date}.json"
        )
        if not path.is_file():
            raise ValueError(f"Missing daily schedule: {path.name}")
        schedule = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schedule, list) or not schedule:
            raise ValueError(f"Invalid or empty daily schedule: {path.name}")
        has_artifact_activity = False
        for index, task in enumerate(schedule):
            if not isinstance(task, dict):
                raise ValueError(f"{path.name} task {index} is not an object")
            time_value = task.get("Time")
            activity = task.get("Activity")
            if not isinstance(time_value, str) or not isinstance(activity, str):
                raise ValueError(
                    f"{path.name} task {index} requires string Time/Activity"
                )
            task_time = parse_clock_time(time_value)
            if not start <= task_time < end:
                raise ValueError(
                    f"{path.name} task {index} is outside working hours"
                )
            errors = activity_validation_errors(
                activity, member_id, member_ids
            )
            if errors:
                raise ValueError(
                    f"{path.name} task {index}: " + "; ".join(errors)
                )
            if _MEETING_RE.search(activity):
                raise ValueError(
                    f"{path.name} task {index} schedules a meeting; use a "
                    "written artifact/email hand-off instead"
                )
            lowered = activity.lower()
            if "break" not in lowered and not is_email_only_activity(activity):
                has_artifact_activity = True
            total_tasks += 1
        if not has_artifact_activity:
            raise ValueError(
                f"{path.name} has no artifact-producing activity"
            )
        artifact_members += 1
    return artifact_members, total_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    members, tasks = validate_day(args.week, args.date)
    print(
        f"Daily run preflight passed: week={args.week} date={args.date} "
        f"members={members} tasks={tasks}"
    )


if __name__ == "__main__":
    main()
