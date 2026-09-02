# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Validate each company-preparation phase without calling the model."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import config
from workday_policy import activity_validation_errors, parse_clock_time


PHASES = (
    "company",
    "profiles",
    "meeting",
    "weekly_schedules",
    "daily_schedules",
)
DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def extract_roles(value):
    roles = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "roles" and isinstance(child, list):
                roles.extend(child)
            else:
                roles.extend(extract_roles(child))
    elif isinstance(value, list):
        for child in value:
            roles.extend(extract_roles(child))
    return roles


def load_company():
    path = Path(config.company_config_path)
    if not path.is_file():
        return None, [], f"missing {path}"
    try:
        company = json.loads(path.read_text(encoding="utf-8"))
        roles = extract_roles(company)
        headcount = sum(int(role.get("count", 0)) for role in roles)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return None, [], f"invalid company JSON: {exc}"
    if not roles:
        return company, [], "company has no roles"
    if headcount != config.employee_number:
        return company, roles, (
            f"headcount={headcount}, expected={config.employee_number}"
        )
    required = {"role_name", "abbr", "count", "outsource", "responsibilities"}
    for role in roles:
        missing = required - role.keys()
        if missing:
            return company, roles, f"role missing fields {sorted(missing)}"
    return company, roles, f"{len(roles)} roles, {headcount} employees"


def expected_members(roles):
    members = {}
    for role in roles:
        for index in range(1, int(role["count"]) + 1):
            members[f"{role['abbr']}-{index}"] = role["role_name"]
    return members


def validate_company():
    company, roles, detail = load_company()
    return company is not None and bool(roles) and detail.endswith("employees"), detail


def validate_profiles():
    _, roles, company_detail = load_company()
    if not roles:
        return False, f"company invalid: {company_detail}"
    expected = expected_members(roles)
    directory = Path(config.profile_output_dir)
    paths = sorted(directory.glob("*.jsonc")) if directory.is_dir() else []
    if {path.stem for path in paths} != set(expected):
        return False, (
            f"profile IDs={sorted(path.stem for path in paths)}, "
            f"expected={sorted(expected)}"
        )

    required = {
        "name",
        "id",
        "ip",
        "age",
        "role",
        "description",
        "tools",
        "mbti",
        "interests",
        "personality",
        "application",
        "email",
        "container_id",
    }
    profiles = []
    try:
        for path in paths:
            profile = json.loads(path.read_text(encoding="utf-8"))
            if required - profile.keys():
                return False, f"{path.name} missing required fields"
            if profile["id"] != path.stem or profile["role"] != expected[path.stem]:
                return False, f"{path.name} ID/role does not match company"
            if not profile["tools"] or not profile["application"]:
                return False, f"{path.name} has empty tools/application"
            profiles.append(profile)
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return False, f"invalid profile: {exc}"

    for field in ("id", "ip", "email"):
        values = [profile[field] for profile in profiles]
        if any(count > 1 for count in Counter(values).values()):
            return False, f"duplicate profile {field}"
    return True, f"{len(profiles)} valid profiles"


def validate_meeting():
    profiles_ok, detail = validate_profiles()
    if not profiles_ok:
        return False, f"profiles invalid: {detail}"
    csv_path = Path(config.meeting_log_dir) / "meeting_response.csv"
    if not csv_path.is_file():
        return False, f"missing {csv_path}"
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        return False, f"invalid meeting CSV: {exc}"
    expected_rows = config.employee_number * config.period
    if len(rows) != expected_rows:
        return False, f"meeting rows={len(rows)}, expected={expected_rows}"
    if any(not row.get("role") or not row.get("content") for row in rows):
        return False, "meeting CSV contains empty role/content"
    expected_assignments = {
        (employee_id, week)
        for employee_id in load_expected_profile_ids()
        for week in range(1, config.period + 1)
    }
    assignments = []
    try:
        for row in rows:
            assignment = json.loads(row.get("assignment", ""))
            if (
                assignment["employee_role"] not in row["role"]
                or assignment["employee_name"] not in row["role"]
            ):
                return False, (
                    "meeting task for "
                    f"{assignment['employee_id']} was handled by {row['role']}"
                )
            assignments.append(
                (assignment["employee_id"], int(assignment["week"]))
            )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False, "meeting CSV has missing/invalid employee-week assignments"
    if len(set(assignments)) != len(assignments):
        return False, "meeting CSV contains duplicate employee-week assignments"
    if set(assignments) != expected_assignments:
        return False, (
            f"meeting assignments={sorted(assignments)}, "
            f"expected={sorted(expected_assignments)}"
        )
    metadata_path = Path(config.meeting_log_dir) / "run_metadata.jsonl"
    latest_event = None
    if metadata_path.is_file():
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("workflow") == "weekly_meeting":
                latest_event = record.get("event")
    if latest_event != "completed":
        return False, (
            "latest weekly meeting event is "
            f"{latest_event!r}, expected 'completed'"
        )
    return True, f"{len(rows)} meeting responses"


def load_expected_profile_ids():
    _, roles, _ = load_company()
    return set(expected_members(roles))


def validate_weekly_schedules():
    meeting_ok, detail = validate_meeting()
    if not meeting_ok:
        return False, f"meeting invalid: {detail}"
    expected_ids = load_expected_profile_ids()
    meeting_mtime = (
        Path(config.meeting_log_dir) / "meeting_response.csv"
    ).stat().st_mtime_ns
    for week in range(1, config.period + 1):
        path = Path(config.meeting_log_dir) / f"meeting_schedule_week_{week}.json"
        if not path.is_file():
            return False, f"missing {path}"
        if path.stat().st_mtime_ns < meeting_mtime:
            return False, f"{path.name} is older than the current meeting"
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"invalid {path.name}: {exc}"
        ids = {row.get("id") for row in rows if isinstance(row, dict)}
        if len(rows) != config.employee_number or ids != expected_ids:
            return False, (
                f"{path.name} IDs={sorted(str(value) for value in ids)}, "
                f"expected={sorted(expected_ids)}"
            )
        for row in rows:
            if row.get("week") != week or not row.get("detailed_goals"):
                return False, f"{path.name} has invalid week/goals"
    return True, f"{config.period} valid weekly schedule files"


def validate_daily_schedules():
    weekly_ok, detail = validate_weekly_schedules()
    if not weekly_ok:
        return False, f"weekly schedules invalid: {detail}"
    expected_ids = load_expected_profile_ids()
    total_files = 0
    missing = []
    for week in range(1, config.period + 1):
        week_dir = Path(config.init_schedule_dir) / f"week_{week}"
        weekly_path = (
            Path(config.meeting_log_dir)
            / f"meeting_schedule_week_{week}.json"
        )
        weekly_mtime = weekly_path.stat().st_mtime_ns
        for member_id in expected_ids:
            paths = [
                week_dir / f"{member_id}_week_{week}_{day}.json"
                for day in DAYS
            ]
            missing_paths = [path.name for path in paths if not path.is_file()]
            if missing_paths:
                missing.extend(missing_paths)
                continue
            for path in paths:
                if path.stat().st_mtime_ns < weekly_mtime:
                    return False, (
                        f"{path.name} is older than the current weekly schedule"
                    )
                try:
                    schedule = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    return False, f"invalid {path.name}: {exc}"
                if not schedule:
                    return False, f"empty daily schedule {path.name}"
                if not isinstance(schedule, list):
                    return False, f"daily schedule is not a list: {path.name}"
                for index, task in enumerate(schedule):
                    if not isinstance(task, dict):
                        return False, f"{path.name} task {index} is not an object"
                    time_value = task.get("Time")
                    activity = task.get("Activity")
                    if (
                        not isinstance(time_value, str)
                        or not isinstance(activity, str)
                        or not activity.strip()
                    ):
                        return False, (
                            f"{path.name} task {index} requires string "
                            "Time and Activity"
                        )
                    try:
                        task_time = parse_clock_time(time_value)
                    except ValueError as exc:
                        return False, f"{path.name} task {index}: {exc}"
                    if not (
                        parse_clock_time(config.workday_start)
                        <= task_time
                        < parse_clock_time(config.workday_end)
                    ):
                        return False, (
                            f"{path.name} task {index} at {time_value} is "
                            "outside working hours"
                        )
                    errors = activity_validation_errors(
                        activity, member_id, expected_ids
                    )
                    if errors:
                        return False, (
                            f"{path.name} task {index} " + "; ".join(errors)
                        )
            total_files += len(paths)
    if missing:
        preview = ", ".join(sorted(missing)[:5])
        suffix = " ..." if len(missing) > 5 else ""
        return False, (
            f"missing {len(missing)} daily schedule files: {preview}{suffix}"
        )
    return True, f"{total_files} valid daily schedule files"


VALIDATORS = {
    "company": validate_company,
    "profiles": validate_profiles,
    "meeting": validate_meeting,
    "weekly_schedules": validate_weekly_schedules,
    "daily_schedules": validate_daily_schedules,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("all", *PHASES), default="all")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    phases = PHASES if args.phase == "all" else (args.phase,)
    all_ok = True
    for phase in phases:
        ok, detail = VALIDATORS[phase]()
        all_ok = all_ok and ok
        if not args.quiet:
            print(f"[{'OK' if ok else 'MISSING'}] {phase}: {detail}")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
