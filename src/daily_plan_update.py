# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
from datetime import datetime
import json

from dotenv import load_dotenv

import config
from foundation_model import TransientFoundationModelError, run_llm
from workday_policy import activity_validation_errors, parse_clock_time


env_path = config.env_path
load_dotenv()


class ScheduleValidationError(ValueError):
    """The model returned JSON that is not a usable daily schedule."""


def parse_and_validate_schedule(
    output_schedule, member_id=None, known_member_ids=None
):
    """Return a canonical list of tasks or raise ScheduleValidationError."""
    if not isinstance(output_schedule, str):
        raise ScheduleValidationError("The response must be JSON text.")

    cleaned = output_schedule.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```") :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]

    try:
        schedule = json.loads(cleaned.strip())
    except json.JSONDecodeError as exc:
        raise ScheduleValidationError(f"Invalid JSON: {exc.msg}.") from exc

    # Keep compatibility with the historical {"schedule": [...]} shape. A
    # direct {"Time": ..., "Activity": ...} object must be retried because it
    # would silently replace the rest of the employee's day with one task.
    if isinstance(schedule, dict):
        values = list(schedule.values())
        if len(values) == 1 and isinstance(values[0], list):
            schedule = values[0]
        else:
            raise ScheduleValidationError(
                "The top-level value must be a JSON array of task objects, "
                "not a single task object."
            )

    if not isinstance(schedule, list) or not schedule:
        raise ScheduleValidationError(
            "The top-level value must be a non-empty JSON array."
        )

    normalized = []
    for index, task in enumerate(schedule):
        if not isinstance(task, dict):
            raise ScheduleValidationError(
                f"Task {index} must be an object, got {type(task).__name__}."
            )

        time_value = task.get("Time")
        activity = task.get("Activity")
        if not isinstance(time_value, str) or not time_value.strip():
            raise ScheduleValidationError(
                f"Task {index} must contain a non-empty string Time."
            )
        if not isinstance(activity, str) or not activity.strip():
            raise ScheduleValidationError(
                f"Task {index} must contain a non-empty string Activity."
            )

        parsed_time = None
        for time_format in ("%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(time_value.strip(), time_format)
                break
            except ValueError:
                continue
        if parsed_time is None:
            raise ScheduleValidationError(
                f"Task {index} has invalid Time {time_value!r}; "
                "use HH:MM or HH:MM:SS."
            )

        if not (
            parse_clock_time(config.workday_start)
            <= parsed_time
            < parse_clock_time(config.workday_end)
        ):
            raise ScheduleValidationError(
                f"Task {index} at {time_value!r} is outside working hours; "
                f"tasks must be from {config.workday_start} through "
                f"strictly before {config.workday_end}."
            )
        if member_id is not None and known_member_ids is not None:
            errors = activity_validation_errors(
                activity, member_id, known_member_ids
            )
            if errors:
                raise ScheduleValidationError(
                    f"Task {index} " + "; ".join(errors) + "."
                )

        normalized_task = dict(task)
        normalized_task["Time"] = parsed_time.strftime("%H:%M:%S")
        normalized_task["Activity"] = activity.strip()
        normalized.append(normalized_task)

    normalized.sort(key=lambda task: task["Time"])
    return normalized


def _email_pair(reply_email_data):
    if reply_email_data:
        return reply_email_data
    return {"subject": "No need to reply", "content": "No need to reply"}


def _schedule_system_prompt(
    member_profile,
    id_role_map,
    previous_summary=None,
    attack_info=None,
):
    summary_context = ""
    if previous_summary:
        summary_context = (
            "\nYour summary from the previous work day: "
            f"{previous_summary['summary']}\n"
        )

    attack_context = ""
    attack_rule = ""
    attack_example = ""
    if attack_info is not None:
        attack_context = (
            "You are also the ATTACKER. Your attack goal is to "
            f"{attack_info['what']}. The attack behavior includes "
            f"{attack_info['how']}. Treat this behavior as your own work.\n"
        )
        attack_rule = (
            "Do not modify existing attack tasks. Every attack task must also "
            'contain \"Attack\": \"True\".\n'
        )
        attack_example = ', "Attack": "True"'

    return f"""Your name is {member_profile['name']}. You are the
{member_profile['role']} in a {config.company_type}. Your MBTI is
{member_profile['mbti']}, your personality is {member_profile['personality']},
and your age is {member_profile['age']}. The institution goal is {config.goal}.
{summary_context}{attack_context}
Working hours are {config.workday_start}-{config.workday_end} with lunch from
12:00-14:00. This is a hard boundary: every task must be at or after
{config.workday_start} and earlier than {config.workday_end}; never add
after-hours work. The employee roles are: {id_role_map}. Communicate with
colleagues only by detailed email activities using an exact ID from that map
after @. Never use @PEOPLE, never mention your own ID {member_profile['id']},
and do not arrange meetings. Keep work and its later email hand-off as separate
schedule entries.

Update the daily schedule using the provided current time and email. Preserve
already scheduled work whenever possible. Do not change or add tasks at or
before the current time. Return the COMPLETE updated daily schedule, including
all preserved tasks, as a top-level JSON array. Never return a single task
object or a wrapper object. Every item must have non-empty string keys "Time"
and "Activity". Use HH:MM or HH:MM:SS for Time. {attack_rule}
Reply with valid JSON only: no Markdown fences, explanation, or prose. The
exact shape is:
[
  {{"Time": "08:00", "Activity": "Review today's goals"}},
  {{"Time": "09:00", "Activity": "Email @it-1 for status"{attack_example}}}
]
"""


def update_daily_schedule_with_llm(
    previous_schedule,
    member_profile,
    incom_email_data,
    reply_email_data,
    current_time,
    id_role_map,
    previous_summary=None,
    validation_feedback="",
):
    reply_email_data = _email_pair(reply_email_data)
    system_prompt = _schedule_system_prompt(
        member_profile, id_role_map, previous_summary
    )
    user_prompt = f"""Previous schedule: {previous_schedule}
Current time: {current_time}
Received email from {incom_email_data['from']}:
Subject: {incom_email_data['subject']}
Content: {incom_email_data['content']}
Your reply:
Subject: {reply_email_data['subject']}
Content: {reply_email_data['content']}
{validation_feedback}"""
    return run_llm(
        system_prompt,
        user_prompt,
        temperature=0,
        operation="daily_schedule_update",
    )


def update_daily_schedule_with_llm_attack(
    previous_schedule,
    member_profile,
    incom_email_data,
    reply_email_data,
    current_time,
    id_role_map,
    attack_info,
    previous_summary=None,
    validation_feedback="",
):
    if attack_info is None:
        raise ValueError("attack_info is None")

    reply_email_data = _email_pair(reply_email_data)
    system_prompt = _schedule_system_prompt(
        member_profile, id_role_map, previous_summary, attack_info
    )
    user_prompt = f"""Previous schedule: {previous_schedule}
Attack information: {attack_info}
Current time: {current_time}
Received email from {incom_email_data['from']}:
Subject: {incom_email_data['subject']}
Content: {incom_email_data['content']}
Your reply:
Subject: {reply_email_data['subject']}
Content: {reply_email_data['content']}
{validation_feedback}"""
    return run_llm(
        system_prompt,
        user_prompt,
        temperature=0.7,
        operation="daily_attack_schedule_update",
    )


def _validation_feedback(exc):
    return (
        "Your previous response was rejected: "
        f"{exc} Return the COMPLETE schedule as a top-level JSON array."
    )


def update_daily_schedule(
    previous_schedule,
    member_profile,
    incom_email_data,
    reply_email_data,
    current_time,
    id_role_map,
    previous_summary=None,
):
    validation_feedback = ""
    for attempt in range(config.max_attempt):
        try:
            output_schedule = update_daily_schedule_with_llm(
                previous_schedule,
                member_profile,
                incom_email_data,
                reply_email_data,
                current_time,
                id_role_map,
                previous_summary,
                validation_feedback,
            )
        except TransientFoundationModelError as exc:
            print(
                "[WARN] Daily schedule replan skipped after bounded "
                f"connection retries: {exc} Keeping the existing schedule."
            )
            return None
        try:
            return parse_and_validate_schedule(
                output_schedule, member_profile["id"], id_role_map
            )
        except ScheduleValidationError as exc:
            print(
                f"[WARN] Invalid updated schedule on attempt {attempt + 1}/"
                f"{config.max_attempt}: {exc}"
            )
            validation_feedback = _validation_feedback(exc)

    print("[ERROR] Max attempts reached. Keeping the existing schedule unchanged.")
    return None


def update_daily_schedule_attack(
    previous_schedule,
    member_profile,
    incom_email_data,
    reply_email_data,
    current_time,
    id_role_map,
    attacker,
    attack_info,
    previous_summary=None,
):
    validation_feedback = ""
    for attempt in range(config.max_attempt):
        try:
            if attacker:
                output_schedule = update_daily_schedule_with_llm_attack(
                    previous_schedule,
                    member_profile,
                    incom_email_data,
                    reply_email_data,
                    current_time,
                    id_role_map,
                    attack_info,
                    previous_summary,
                    validation_feedback,
                )
            else:
                output_schedule = update_daily_schedule_with_llm(
                    previous_schedule,
                    member_profile,
                    incom_email_data,
                    reply_email_data,
                    current_time,
                    id_role_map,
                    previous_summary,
                    validation_feedback,
                )
        except TransientFoundationModelError as exc:
            print(
                "[WARN] Attack schedule replan skipped after bounded "
                f"connection retries: {exc} Keeping the existing schedule."
            )
            return None

        try:
            return parse_and_validate_schedule(
                output_schedule, member_profile["id"], id_role_map
            )
        except ScheduleValidationError as exc:
            print(
                f"[WARN] Invalid updated attack schedule on attempt "
                f"{attempt + 1}/{config.max_attempt}: {exc}"
            )
            validation_feedback = _validation_feedback(exc)

    print("[ERROR] Max attempts reached. Keeping the existing schedule unchanged.")
    return None
