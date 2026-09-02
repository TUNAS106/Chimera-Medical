# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
from camel.agents.chat_agent import ChatAgent
from camel.messages.base import BaseMessage
from camel.societies.workforce import Workforce
from camel.tasks.task import Task
from camel.toolkits import (
    FunctionTool,
    SearchToolkit,
)
import logging
import os
from datetime import datetime, timezone
from camel.logger import set_log_level

import config
import json
from model_backend import (
    create_camel_model,
    model_runtime_description,
    write_run_metadata,
)


from dotenv import load_dotenv

env_path = config.env_path
load_dotenv(env_path)

set_log_level(level="DEBUG")


def process_task_logging(workforce: Workforce, task: Task, log_dir: str) -> Task:
    """
    Run the `process_task` method of a Workforce instance and capture all logger outputs.

    Args:
        workforce (Workforce): The Workforce instance.
        task (Task): The task to be processed.
        log_dir (str): The directory to save the log file.

    Returns:
        Task: The updated task after processing.
    """
    # Ensure the log directory exists
    os.makedirs(log_dir, exist_ok=True)
    # The patched CAMEL worker uses this path for meeting_response.csv. Keep
    # worker output inside the active scenario instead of the legacy demo path.
    os.environ["CAMEL_WORKFORCE_MEETING_LOG_DIR"] = log_dir
    log_file_path = os.path.join(log_dir, "meeting_detailed_actions.log")

    # Configure a FileHandler for the logger
    file_handler = logging.FileHandler(log_file_path, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    # Add the FileHandler to the logger
    logger = logging.getLogger()  # Get the root logger
    logger.addHandler(file_handler)

    try:
        logger.info("MEETING_START %s task=%r", model_runtime_description(), task.content)
        # Run the process_task method
        result_task = workforce.process_task(task)
        logger.info("MEETING_COMPLETE result=%r", result_task.result)
    except Exception as exc:
        logger.exception("MEETING_FAILED")
        write_run_metadata(
            log_dir,
            "weekly_meeting",
            event="failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    finally:
        # Remove the FileHandler after execution to avoid duplicate logs
        logger.removeHandler(file_handler)
        file_handler.close()

    return result_task


def load_member_profile(
    member_profile_path: str,
    search_tools: list,
):
    with open(member_profile_path, "r") as f:
        member_profile = json.load(f)

    member_agent = ChatAgent(
        BaseMessage.make_assistant_message(
            role_name=member_profile["role"],
            content=f"""You are the {member_profile['role']} in a {config.company_type}.
            As a {member_profile['role']}, you are assigned to {member_profile['description']}.
            Your personality is {member_profile['personality']}.""",
        ),
        model=create_camel_model(temperature=0),
        tools=[*search_tools],
    )
    return member_profile, member_agent


def WeeklyPlan(member_dir: str):
    search_tools = []
    if config.meeting_enable_search and not config.offline_mode:
        search_toolkit = SearchToolkit()
        search_tools = [
            FunctionTool(search_toolkit.search_google),
            FunctionTool(search_toolkit.search_duckduckgo),
        ]

    agent_kwargs = {
        "model": create_camel_model(temperature=0),
    }

    workforce = Workforce(
        "Meeting for weekly schedule",
        coordinator_agent_kwargs=agent_kwargs,
        task_agent_kwargs=agent_kwargs,
        new_worker_agent_kwargs=agent_kwargs,
    )

    all_roles = set()
    id_role_map = {}
    members = []
    workforce_node_ids = {}

    for file in sorted(os.listdir(member_dir)):
        if file.endswith(".jsonc"):
            member_profile_path = os.path.join(member_dir, file)
            member_profile, member_agent = load_member_profile(
                member_profile_path,
                search_tools,
            )
            all_roles.add(member_profile["role"])  # add roles
            id_role_map[member_profile["id"]] = member_profile[
                "role"
            ]  # add id-role map
            members.append(member_profile)
            member_description = f"{member_profile['role']}-{member_profile['name']}"
            workforce.add_single_agent_worker(member_description, worker=member_agent)
            workforce_node_ids[member_profile["id"]] = workforce._children[
                -1
            ].node_id

    # specify the task to be solved
    human_task = Task(
        content=f"""The company has {config.employee_number} employees with {len(all_roles)} type of roles:
        **{all_roles}**. The employee id and their role are as follows: {id_role_map}.
        The company is planning to have a meeting to discuss the weekly goals for each employee.
        The overall goal here is to settle plans for each employee for the next **{config.period}** weeks to **{config.goal}**.
        Everyone should actively participate in the discussion and have the detailed plan for each week.
        Every employee should have their own goals and tasks for each week, and they do not need to execute at this time.
        You should provide detailed expected goals for **each week for each member(agent)**.
        The output format should be as the pandas DataFrame with {config.employee_number} rows (for each member of the company) and {config.period+1} columns (for each week starting from Week1).
        Each cell should contain the detailed expected goals for each member for that week.""",
        # subtasks=[Task(content="The output format should be a table with 4 columns: Week, Developer, Designer, Product Manager. Each column should contain the expected goals for each role for that week.")],
        id="0",
    )

    # One deterministic work item per employee/week. Model-driven Workforce
    # decomposition is useful for open-ended work, but it does not guarantee
    # the exact employee_number * period rows required by schedule generation.
    task_index = 0
    for member in members:
        for week in range(1, config.period + 1):
            assignment = {
                "employee_id": member["id"],
                "employee_name": member["name"],
                "employee_role": member["role"],
                "week": week,
                "workforce_assignee_id": workforce_node_ids[member["id"]],
            }
            subtask = Task(
                content=f"""Define the detailed goals for Week {week} only for
employee {member['id']} ({member['role']} - {member['name']}). The goals must
directly support this company objective: {config.goal}. Provide concrete,
measurable activities and deliverables that fit this employee's role. Coordinate
with relevant goals from earlier meeting contributions when available. Do not
create goals for another employee or another week, and do not delegate this task.""",
                id=f"0.{task_index}",
                additional_info=json.dumps(assignment, ensure_ascii=False),
            )
            human_task.add_subtask(subtask)
            task_index += 1

    expected_task_count = config.employee_number * config.period
    if len(human_task.subtasks) != expected_task_count:
        raise ValueError(
            f"Prepared {len(human_task.subtasks)} meeting tasks; expected "
            f"{expected_task_count}."
        )

    log_dir = config.meeting_log_dir
    os.makedirs(log_dir, exist_ok=True)
    # A retry must replace an incomplete meeting instead of appending to it.
    for filename in ("meeting_response.csv", "meeting_result.log"):
        output_path = os.path.join(log_dir, filename)
        if os.path.exists(output_path):
            os.remove(output_path)
    write_run_metadata(
        log_dir,
        "weekly_meeting",
        event="started",
        member_count=len(id_role_map),
        task_count=len(human_task.subtasks),
    )
    task_discuss = process_task_logging(workforce, human_task, log_dir)
    write_run_metadata(
        log_dir, "weekly_meeting", event="completed", member_count=len(id_role_map)
    )

    print("Final Result of Original task:\n", task_discuss.result)
    # save task_discuss.result to a file
    with open(os.path.join(log_dir, "meeting_result.log"), "w") as f:
        f.write(f"=== Meeting run {datetime.now(timezone.utc).isoformat()} ===\n")
        f.write(task_discuss.result)
        f.write("\n")

    # move /data/meeting_logs/* to log_dir if the path exists
    meeting_logs_src = "/data/meeting_logs"
    if os.path.exists(meeting_logs_src):
        import shutil

        for item in os.listdir(meeting_logs_src):
            shutil.move(os.path.join(meeting_logs_src, item), log_dir)


if __name__ == "__main__":
    WeeklyPlan(
        member_dir=config.profile_output_dir,
    )
