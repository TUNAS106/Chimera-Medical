# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
from dotenv import load_dotenv

import config
import json
import os

from tqdm import tqdm
from foundation_model import run_llm
from workday_policy import activity_validation_errors, parse_clock_time

env_path = config.env_path
load_dotenv()

days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def export_weekly_schedule_to_daily(
    init_schedule_dir: str,
    week_id: int,
    employee_id: str,
    id_role_map: dict,
    profile_list: list,
):
    week_dir = os.path.join(init_schedule_dir, f"week_{week_id}")
    if not os.path.exists(week_dir):
        os.makedirs(week_dir)

    # load the json file
    week_file = os.path.join(
        config.meeting_log_dir, f"meeting_schedule_week_{week_id}.json"
    )
    with open(week_file, "r") as f:
        data = json.load(f)

    for employee in data:
        if employee["id"] == employee_id:
            # load the json file
            weekly_goal = employee["detailed_goals"]

    for member_profile in profile_list:
        if member_profile["id"] == employee_id:
            profile_detail = member_profile
            break

    previous_error = ""
    for attempt in range(config.max_attempt):
        # generate the daily plan
        output = generate_daily_plan_with_llm(
            week_id=week_id,
            profile_detail=profile_detail,
            id_role_map=id_role_map,
            weekly_goal=weekly_goal,
            previous_error=previous_error,
        )

        if "```json" in output:
            output = output.replace("```json", "").replace("```", "").strip()

        # check if the output is valid JSON
        try:
            daily_week_schedule = json.loads(output)
            if not isinstance(daily_week_schedule, dict):
                raise ValueError("Daily schedule must be a JSON object.")
            missing_days = [day for day in days if day not in daily_week_schedule]
            if missing_days:
                raise ValueError(f"Missing days: {missing_days}")
            for day in days:
                tasks = daily_week_schedule[day]
                if not isinstance(tasks, list) or not tasks:
                    raise ValueError(f"{day} must contain at least one task.")
                for task in tasks:
                    if not isinstance(task, dict):
                        raise ValueError(f"{day} contains a non-object task.")
                    if not task.get("Time") or not task.get("Activity"):
                        raise ValueError(
                            f"{day} task is missing Time or Activity: {task}"
                        )
                    task_time = parse_clock_time(task["Time"])
                    if not (
                        parse_clock_time(config.workday_start)
                        <= task_time
                        < parse_clock_time(config.workday_end)
                    ):
                        raise ValueError(
                            f"{day} task is outside working hours: {task}"
                        )
                    activity_errors = activity_validation_errors(
                        task["Activity"], employee_id, id_role_map
                    )
                    if activity_errors:
                        raise ValueError(
                            f"{day} task {'; '.join(activity_errors)}: {task}"
                        )
            break
        except Exception as e:
            print("[WARN] Error parsing JSON:", e, "Retrying...")
            previous_error = str(e)
            if attempt == config.max_attempt - 1:
                print("[Error] Max attempts reached. Exiting.")
                print(f"### Errored JSON ### : {output}")
                raise e

    # save the JSON to init_schedule/

    for day in days:
        if day in daily_week_schedule and daily_week_schedule[day]:
            # save the json to init_schedule/
            day_file = os.path.join(
                week_dir, f"{employee_id}_week_{week_id}_{day}.json"
            )
            with open(day_file, "w") as fd:
                json.dump(daily_week_schedule[day], fd, indent=4)


def generate_daily_plan_with_llm(
    week_id: int,
    profile_detail: dict,
    id_role_map,
    weekly_goal: str,
    previous_error: str = "",
):
    system_prompt = f"""Your name is {profile_detail['name']}. Your personality is {profile_detail['mbti']}, and your age is {profile_detail['age']}.
                You are a {profile_detail['role']} in a {config.company_type}.
                The goal of your company is {config.goal}. \n\n
                I will provide you with your goal plan for this week after you meet with all the members in the company, and you should divide these tasks into a **very detailed** schedule for your daily work. \n\n
                There are {config.employee_number} members in your company, and the detailed role distribution can be found as follows: {id_role_map}. \n\n
                You can contact colleagues only by email. Use one or more exact colleague IDs from {list(id_role_map)} after @, never @PEOPLE, never your own ID @{profile_detail['id']}, and never an unknown role or name. Do not schedule meetings. Keep artifact-producing work and email hand-off as separate entries: first create and verify a report, then in a later entry email an exact colleague ID with its verified findings.\n\n
                Working hours are a hard boundary from {config.workday_start} through {config.workday_end}: every activity must be at or after {config.workday_start} and strictly before {config.workday_end}. Lunch is 12:00-14:00; only a break or idle activity may be scheduled then. **You should act based on your characteristics and your own personal preferences to handle your work**.\n\n
                When you are not into working, you can loaf around by browsing websites you are interested in, or doing nothing with yourself. \n\n
                **You should organize your activity timetable into a JSON format for the whole week with the necessary keys including \\\"Time\\\" and \\\"Activity\\\"**\n\n
                Example: {{\"Monday\": [{{\"Time\": \"08:00\", \"Activity\": \"Create and verify the daily data-quality report\"}}, {{\"Time\": \"09:00\", \"Activity\": \"Email @data-1 with the verified report findings and request review\"}}]}}.\n\n
                The response should be in the JSON format, with very detailed information regarding on what time, specifically what you are doing. **You should only return the JSON file without any other sentences**. \n\n"""
    system_prompt += (
        "\nHard constraint: include all seven keys Monday, Tuesday, Wednesday, "
        "Thursday, Friday, Saturday, and Sunday, with at least one activity "
        "for every day.\n"
    )
    retry_instruction = (
        f"\nThe previous output failed validation: {previous_error}. "
        "Return a corrected complete seven-day JSON object.\n"
        if previous_error
        else ""
    )
    user_prompt = f"""The detailed goal for the employee for week {week_id} is as follows: {weekly_goal}.\n\n{retry_instruction}"""

    llm_output = run_llm(
        system_prompt, user_prompt, operation="daily_plan_generation"
    )
    return llm_output


if __name__ == "__main__":
    # mkdir of the init_schedule directory
    init_schedule_dir = config.init_schedule_dir
    if not os.path.exists(init_schedule_dir):
        os.makedirs(init_schedule_dir)

    ########################
    # Get the total employee info
    id_role_map = {}
    id_list = []
    profile_list = []

    member_dir = config.profile_output_dir
    for file in os.listdir(member_dir):
        if file.endswith(".jsonc"):
            member_profile_path = os.path.join(member_dir, file)
            with open(member_profile_path, "r") as f:
                member_profile = json.load(f)
            id_role_map[member_profile["id"]] = member_profile[
                "role"
            ]  # add id-role map
            id_list.append(member_profile["id"])
            profile_list.append(member_profile)  # add profile
    ########################

    # for single employee single week
    # week_id = 2
    # employee_id = "cdev-1"
    # export_weekly_schedule_to_daily(init_schedule_dir, week_id, employee_id, id_role_map, profile_list)

    # For every employee and each week
    for week_id in tqdm(
        range(1, config.period + 1), desc="Generating weekly schedule... "
    ):
        for employee_id in tqdm(
            id_list, desc=f"Processing employees for week {week_id}", leave=False
        ):
            export_weekly_schedule_to_daily(
                init_schedule_dir, week_id, employee_id, id_role_map, profile_list
            )

    # post check
    # BASH: for i in init_schedule/*; do ls ${i} | wc -l; done
