# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
#
# export run_task to support LLM agent operation, init with CamelAI
#

import fcntl
import hashlib
import json
import os
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# from dotenv import load_dotenv

from camel.toolkits import (
    BrowserToolkit,
    FileWriteToolkit,
    TerminalToolkit,
    # ImageAnalysisToolkit,
    # VideoAnalysisToolkit,
    # CodeExecutionToolkit,
)
from camel.logger import set_log_level
from camel.types import RoleType

# from owl.utils import run_society
from owl.utils import run_chimera_society  # , DocumentProcessingToolkit
from camel.societies import RolePlaying

import config
from model_backend import (
    create_camel_model,
    model_runtime_description,
    safe_endpoint_label,
)
from simulation_workspace import (
    build_simulation_task_prompt,
    prepare_simulation_workspace,
)
from web_search import fetch_url, search_web

set_log_level(level="DEBUG")


_CHIMERA_ASSISTANT_SYSTEM_PROMPT = """===== CHIMERA ACTIVITY EXECUTOR =====
You are the {assistant_role}; the {user_role} is a task reviewer. Complete the
following bounded activity in its isolated simulation workspace:

{task}

Follow the simulation contract exactly. Use tools for every claimed file read,
write, command, search, or verification. Never say a file was created unless a
tool successfully created it, and never treat empty/failed output as success.
Use `file_read` to read a known local file and `write_file` to save an artifact.
When the path is already known, do not search for it with `file_find_by_name` or
`file_find_in_content`. Never print a `<tool_call>` block as ordinary text.
Do not request real credentials or access live systems. Prefer one useful,
role-appropriate artifact over a long explanation. You MUST create or update
that artifact with a file-writing tool and verify the saved file before using
the completion marker. After every final write, use `file_read` on that exact
artifact path so the reviewer can verify the saved content. Reading an input or
describing intended output alone is never completion. For small local inputs,
inspect the complete file rather than sampling only its first lines.

For public-web research, call `search_web` first and pass only an exact URL
returned by that call to `fetch_url`. Stop fetching after two failures. Search
snippets may be summarized, but clearly label any claim that could not be
verified from fetched page text. Never invent or guess a URL.

Respond to each reviewer instruction with `Solution:` and the concrete work or
tool result. Do not automatically append `Next request`. Once the overall
scheduled activity has a real artifact or a complete verified result, report
its path and key finding and end with the exact marker
`CHIMERA_TASK_COMPLETE`. Do not use that marker before the work is complete.
"""

_CHIMERA_USER_SYSTEM_PROMPT = """===== CHIMERA ACTIVITY REVIEWER =====
You are the {user_role}; the {assistant_role} executes tools. Drive this
bounded simulated activity to completion:

{task}

The local simulation workspace is the complete authorized environment. Never
ask for real credentials, live EHR/network/email access, package installation,
or files outside that workspace. Your FIRST instruction must request one
end-to-end action: inspect the necessary local input, create a named artifact
that answers the scheduled activity, and verify the saved file. Use at most
three substantive instructions. Do not repeat a failed instruction. Reading an
input is not completion, and you must not accept a completion marker unless the
executor reports a successful file-writing tool result and the verified
artifact path. Require a successful `file_read` of the final artifact after its
last write; otherwise issue one concrete verification instruction.

When a local path is known, explicitly instruct the executor to use `file_read`
and then `write_file`. Do not ask it to search for a known seed filename.

If the executor response contains `CHIMERA_TASK_COMPLETE` with a completed
artifact/result, reply only `TASK_DONE`. Otherwise reply only in this form:
Instruction: <one concrete next action that advances or finishes the activity>
Input: <needed local input or None>
"""


class TaskIncompleteError(RuntimeError):
    """Raised after an incomplete/blocked task has been audited cleanly."""

    def __init__(self, semantic_status: str, member_id: str, event_index: int):
        self.semantic_status = semantic_status
        self.member_id = member_id
        self.event_index = event_index
        super().__init__(
            f"Task ended with semantic status {semantic_status}: "
            f"member={member_id} event_index={event_index}"
        )


def _task_completion_status(
    answer: Any,
    chat_history: Any,
    completion_info: Optional[dict] = None,
) -> str:
    """Classify semantic completion instead of treating no exception as success."""

    # A tool loop can produce a large history.  Completion markers occur near
    # the final response, so cap this classification copy to protect memory.
    final_history = chat_history[-1:] if isinstance(chat_history, list) else []
    final_history_text = json.dumps(
        final_history, ensure_ascii=False, default=str
    )
    final_text = f"{answer}\n{final_history_text[-20000:]}".lower()
    if "chimera_blocked_captcha" in final_text or (
        "status" in final_text
        and "blocked" in final_text
        and "captcha" in final_text
    ):
        return "blocked"
    incomplete_markers = (
        "task is not completed within the round limit",
        "task has not been completed within the round limit",
        "not been completed within the round limit",
        "could not complete the task",
    )
    if any(marker in final_text for marker in incomplete_markers):
        return "incomplete"
    if completion_info is not None:
        reviewer_signal = bool(completion_info.get("completion_signal"))
        assistant_signal = bool(
            completion_info.get("assistant_completion_signal")
        )
    else:
        reviewer_signal = "task_done" in final_text
        assistant_signal = "chimera_task_complete" in final_text
    if not reviewer_signal or not assistant_signal:
        return "incomplete"
    return "success"


def _required_artifact_is_verified(
    required_artifact: str, artifact_verification: Any
) -> bool:
    """Return whether the exact required event artifact was verified."""

    if not isinstance(required_artifact, str) or not required_artifact:
        return False
    if not isinstance(artifact_verification, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("path") == required_artifact
        and isinstance(item.get("size_bytes"), int)
        and item["size_bytes"] > 0
        for item in artifact_verification
    )


def _append_task_transcript(log_dir: str, record: dict) -> None:
    """Persist one complete agent task safely across worker processes."""

    transcript_path = os.path.join(log_dir, "task_transcripts.jsonl")
    payload = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with open(transcript_path, "a", encoding="utf-8") as transcript_file:
        fcntl.flock(transcript_file.fileno(), fcntl.LOCK_EX)
        try:
            transcript_file.write(payload)
            transcript_file.flush()
        finally:
            fcntl.flock(transcript_file.fileno(), fcntl.LOCK_UN)


def _safe_append_task_transcript(log_dir: str, record: dict) -> None:
    try:
        _append_task_transcript(log_dir, record)
    except OSError:
        logging.getLogger(__name__).exception(
            "Unable to append the task transcript audit record"
        )


def _workspace_snapshot(
    output_dir: str, excluded_paths: set[str]
) -> dict[str, str]:
    """Hash task-created files so a verbal completion cannot pass as work."""

    snapshot: dict[str, str] = {}
    for root, _, filenames in os.walk(output_dir):
        for filename in filenames:
            path = os.path.abspath(os.path.join(root, filename))
            if (
                path in excluded_paths
                or os.path.islink(path)
                or not os.path.isfile(path)
            ):
                continue
            digest = hashlib.sha256()
            try:
                with open(path, "rb") as artifact_file:
                    for chunk in iter(lambda: artifact_file.read(65536), b""):
                        digest.update(chunk)
            except OSError:
                continue
            snapshot[os.path.relpath(path, output_dir)] = digest.hexdigest()
    return snapshot


def _artifact_verification(
    output_dir: str, changed_artifacts: list[str], digests: dict[str, str]
) -> list[dict[str, Any]]:
    """Return post-write filesystem evidence for non-empty regular files."""

    verified: list[dict[str, Any]] = []
    output_root = os.path.realpath(output_dir)
    for relative_path in changed_artifacts:
        artifact_path = os.path.realpath(
            os.path.join(output_root, relative_path)
        )
        try:
            if os.path.commonpath([output_root, artifact_path]) != output_root:
                continue
            size_bytes = os.path.getsize(artifact_path)
        except (OSError, ValueError):
            continue
        if size_bytes <= 0:
            continue
        verified.append(
            {
                "path": relative_path,
                "size_bytes": size_bytes,
                "sha256": digests[relative_path],
            }
        )
    return verified


def construct_society(
    question: str, output_dir: str, temperature: float = 0
) -> RolePlaying:
    r"""Construct a society of agents based on the given question.

    Args:
        question (str): The task or question to be addressed by the society.
        output_dir (str): Directory for intermediate files and results.
        temperature (float): Sampling temperature. Use 0 for deterministic
            operations (scheduling, meetings) and 0.7 for creative or
            strategic tasks (attack execution, multi-step planning).

    Returns:
        RolePlaying: A configured society of agents ready to address the
            question.
    """

    # Create models for different components
    models = {
        "user": create_camel_model(temperature=temperature),
        "assistant": create_camel_model(temperature=temperature),
        "browsing": create_camel_model(temperature=0),
        "planning": create_camel_model(temperature=0),
    }

    # Configure toolkits.  Keep live toolkit objects attached to the society so
    # run_task() can always clean them up, including error and timeout paths.
    terminal_toolkit = TerminalToolkit(
        working_dir=output_dir, log_path=output_dir, need_terminal=False
    )
    browser_toolkit: Optional[BrowserToolkit] = None
    tools = [
        *FileWriteToolkit(output_dir=output_dir).get_tools(),
        *terminal_toolkit.get_tools(),
    ]
    if config.web_mode == "search_only":
        tools += [search_web, fetch_url]
    elif config.web_mode == "browser":
        try:
            browser_toolkit = BrowserToolkit(
                headless=True,
                web_agent_model=models["browsing"],
                planning_agent_model=models["planning"],
                cache_dir=output_dir,
            )
        except Exception:
            # Browser construction can fail after Playwright has started.  The
            # patched toolkit is idempotent, but there may be no object to close
            # if __init__ itself failed, so propagate after best-effort cleanup.
            if browser_toolkit is not None:
                browser_toolkit.close()
            raise
        tools += [*browser_toolkit.get_tools(), search_web, fetch_url]

    # Configure agent roles and parameters
    user_agent_kwargs = {"model": models["user"]}
    assistant_agent_kwargs = {
        "model": models["assistant"],
        "tools": tools,
        "max_tool_iterations": config.activity_max_tool_iterations,
    }

    # Configure task parameters
    task_kwargs = {
        "task_prompt": question,
        "with_task_specify": False,
    }

    # Create and return the society
    society = RolePlaying(
        **task_kwargs,
        user_role_name="user",
        user_agent_kwargs=user_agent_kwargs,
        assistant_role_name="assistant",
        assistant_agent_kwargs=assistant_agent_kwargs,
        sys_msg_generator_kwargs={
            "sys_prompts": {
                RoleType.ASSISTANT: _CHIMERA_ASSISTANT_SYSTEM_PROMPT,
                RoleType.USER: _CHIMERA_USER_SYSTEM_PROMPT,
            },
            "sys_msg_meta_dict_keys": {
                "task",
                "assistant_role",
                "user_role",
            },
        },
    )

    # These are private Chimera lifecycle hooks, not CAMEL agent tools.
    society._chimera_browser_toolkit = browser_toolkit
    society._chimera_terminal_toolkit = terminal_toolkit

    return society


def run_task(
    week: int,
    date: str,
    task: str,
    member_id: str,
    log_dir: str,
    event_index: int,
    output_dir: str,
    temperature: float = 0,
    semantic_attempt: int = 1,
) -> str:
    r"""Run the OWL system with a given task.

    Args:
        task (str): The task or question to be addressed.
        temperature (float): Sampling temperature passed to construct_society.
            Use 0 for deterministic tasks and 0.7 for attack/strategic tasks.

    Returns:
        str: The answer generated by the society.
    """
    # output_dir saves all the intermediate files and result during the execution
    os.makedirs(log_dir, exist_ok=True)
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    detailed_log = os.path.join(
        log_dir, f"{member_id}_week_{week}_{date}_executio_task_{event_index}.log"
    )
    # Configure a FileHandler for the logger
    # Append instead of overwriting an earlier run of the same simulated task.
    file_handler = logging.FileHandler(detailed_log, mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    logger = logging.getLogger()
    logger.addHandler(file_handler)

    society = None
    answer = ""
    task_status = "error"
    try:
        logger.info(
            "TASK_START run_id=%s member=%s week=%s date=%s event_index=%s %s prompt=%r",
            run_id,
            member_id,
            week,
            date,
            event_index,
            model_runtime_description(),
            task,
        )
        # Construct after attaching the handler so model/tool initialization is
        # included in this task's detailed audit log.
        seed_files = prepare_simulation_workspace(
            output_dir,
            member_id=member_id,
            week=week,
            date=date,
        )
        excluded_seed_paths = {
            os.path.abspath(path) for path in seed_files.values()
        }
        workspace_before = _workspace_snapshot(
            output_dir, excluded_seed_paths
        )
        required_artifact = (
            f"activity_{member_id}_week_{week}_{date}_event_"
            f"{event_index}_attempt_{semantic_attempt}.md"
        )
        execution_prompt = build_simulation_task_prompt(
            task, output_dir, required_artifact=required_artifact
        )
        society = construct_society(execution_prompt, output_dir, temperature)
        answer, chat_history, token_count = run_chimera_society(
            society,
            round_limit=config.round_limit,
            member_id=member_id,
            log_dir=log_dir,
            event_index=event_index,
            week=week,
            date=date,
        )
        task_status = _task_completion_status(
            answer,
            chat_history,
            token_count,
        )
        workspace_after = _workspace_snapshot(output_dir, excluded_seed_paths)
        changed_artifacts = sorted(
            path
            for path, digest in workspace_after.items()
            if workspace_before.get(path) != digest
        )
        artifact_verification = _artifact_verification(
            output_dir, changed_artifacts, workspace_after
        )
        if task_status == "success" and not _required_artifact_is_verified(
            required_artifact, artifact_verification
        ):
            task_status = "incomplete"
            token_count["completion_signal"] = False
            token_count["termination_reason"] = (
                "required_artifact_not_verified"
            )
        logger.info(
            "TASK_COMPLETE run_id=%s member=%s event_index=%s status=%s "
            "token_count=%s answer=%r",
            run_id,
            member_id,
            event_index,
            task_status,
            token_count,
            answer,
        )
        transcript = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "status": task_status,
            "member_id": member_id,
            "week": week,
            "date": date,
            "event_index": event_index,
            "provider": config.foundation_corp,
            "model": config.foundation_model,
            "endpoint": safe_endpoint_label(),
            "temperature": temperature,
            "semantic_attempt": semantic_attempt,
            "required_artifact": required_artifact,
            "token_usage": token_count,
            "simulation_contract": True,
            "changed_artifacts": changed_artifacts,
            "artifact_verification": artifact_verification,
        }
        if config.log_model_content:
            transcript.update(
                {
                    "task_prompt": task,
                    "answer": answer,
                    "chat_history": chat_history,
                }
            )
        _safe_append_task_transcript(log_dir, transcript)
    except Exception as exc:
        logger.exception(
            "TASK_FAILED run_id=%s member=%s event_index=%s",
            run_id,
            member_id,
            event_index,
        )
        failure = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "status": "error",
            "member_id": member_id,
            "week": week,
            "date": date,
            "event_index": event_index,
            "provider": config.foundation_corp,
            "model": config.foundation_model,
            "endpoint": safe_endpoint_label(),
            "temperature": temperature,
            "semantic_attempt": semantic_attempt,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if config.log_model_content:
            failure["task_prompt"] = task
        _safe_append_task_transcript(log_dir, failure)
        raise
    finally:
        if society is not None:
            browser_toolkit = getattr(
                society, "_chimera_browser_toolkit", None
            )
            if browser_toolkit is not None:
                try:
                    browser_toolkit.close()
                except Exception:
                    logger.exception("Unable to close BrowserToolkit cleanly")
            terminal_toolkit = getattr(
                society, "_chimera_terminal_toolkit", None
            )
            if terminal_toolkit is not None and hasattr(terminal_toolkit, "close"):
                try:
                    terminal_toolkit.close()
                except Exception:
                    logger.exception("Unable to clean up TerminalToolkit")
        # Remove the file handler after use
        logger.removeHandler(file_handler)
        file_handler.close()

    if task_status != "success":
        raise TaskIncompleteError(task_status, member_id, event_index)
    return answer


if __name__ == "__main__":
    # r"""Main function to run the OWL system with an example question."""
    # # Default research question
    default_task = "Navigate to camel.ai, count the paper numbers has been published. No need to verify your answer."

    # # Override default task if command line argument is provided
    # task = sys.argv[1] if len(sys.argv) > 1 else default_task

    # # Construct and run the society
    # society = construct_society(task)
    # answer, chat_history, token_count = run_society(society)

    # # Output the result
    # print(f"\033[94mAnswer: {answer}\033[0m")
