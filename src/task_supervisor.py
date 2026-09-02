# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Bounded process supervision for daily employee activities.

The original scheduler created one ``multiprocessing.Process`` for every
activity and never joined it.  A simulated day could therefore leave dozens of
Python, Playwright and Chromium trees alive at once.  This supervisor queues
plain task descriptions and materializes at most ``max_concurrent`` child
processes, with a hard wall-clock timeout for every started activity.
"""

from __future__ import annotations

import multiprocessing
import json
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List


@dataclass(frozen=True)
class TaskSpec:
    week: int
    date: str
    task: str
    member_id: str
    log_dir: str
    event_index: int
    output_dir: str
    temperature: float = 0

    @property
    def label(self) -> str:
        return (
            f"{self.member_id}:week={self.week}:date={self.date}:"
            f"event={self.event_index}"
        )


@dataclass
class _ActiveTask:
    spec: TaskSpec
    process: multiprocessing.Process
    started_monotonic: float


def _execute_task_spec(spec: TaskSpec) -> None:
    """Child-process entry point kept outside the daily ``__main__`` module."""

    # Give every activity its own process group.  A hard timeout can then stop
    # the Python worker together with Playwright/Chromium descendants instead
    # of leaving orphan browser processes consuming the container memory.
    try:
        os.setsid()
    except OSError:
        pass

    # Import in the child so the spawn parent does not need to pickle CAMEL
    # model/toolkit objects or a live Logger instance.
    import config
    from task import TaskIncompleteError, run_task

    max_attempts = 1 + config.activity_semantic_retries
    for semantic_attempt in range(1, max_attempts + 1):
        task_prompt = spec.task
        if semantic_attempt > 1:
            task_prompt += (
                "\n\nREPAIR ATTEMPT: The previous attempt ended before a "
                "new artifact was verified. Complete the original activity, "
                "write the exact required attempt artifact with a file tool, "
                "and read it back after the final write. Reading a seed file "
                "alone is not completion."
            )
            print(
                f"[WARN] TASK_SEMANTIC_RETRY {spec.label} "
                f"attempt={semantic_attempt}/{max_attempts}"
            )
        try:
            run_task(
                spec.week,
                spec.date,
                task_prompt,
                spec.member_id,
                spec.log_dir,
                spec.event_index,
                output_dir=spec.output_dir,
                temperature=spec.temperature,
                semantic_attempt=semantic_attempt,
            )
            return
        except TaskIncompleteError as exc:
            if (
                exc.semantic_status != "incomplete"
                or semantic_attempt >= max_attempts
            ):
                raise


class TaskSupervisor:
    """Run a bounded number of activity processes and collect failures."""

    def __init__(
        self,
        max_concurrent: int,
        timeout_seconds: float,
        terminate_grace_seconds: float = 10,
    ) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.timeout_seconds = max(30.0, float(timeout_seconds))
        self.terminate_grace_seconds = max(
            1.0, float(terminate_grace_seconds)
        )
        self._context = multiprocessing.get_context("spawn")
        self._condition = threading.Condition()
        self._pending: Deque[TaskSpec] = deque()
        self._active: Dict[int, _ActiveTask] = {}
        self._accepting = True
        self._abort_requested = False
        self._submitted_count = 0
        self._completed_count = 0
        self._failures: List[Dict[str, Any]] = []
        self._results: Dict[str, Dict[str, Any]] = {}
        self._thread = threading.Thread(
            target=self._run,
            name="chimera-task-supervisor",
            daemon=False,
        )
        self._thread.start()

    @property
    def submitted_count(self) -> int:
        with self._condition:
            return self._submitted_count

    @property
    def completed_count(self) -> int:
        with self._condition:
            return self._completed_count

    @property
    def failures(self) -> List[Dict[str, Any]]:
        with self._condition:
            return list(self._failures)

    def submit(
        self,
        *,
        week: int,
        date: str,
        task: str,
        member_id: str,
        log_dir: str,
        event_index: int,
        output_dir: str,
        temperature: float = 0,
    ) -> str:
        spec = TaskSpec(
            week=week,
            date=date,
            task=task,
            member_id=member_id,
            log_dir=log_dir,
            event_index=event_index,
            output_dir=output_dir,
            temperature=temperature,
        )
        with self._condition:
            if not self._accepting:
                raise RuntimeError("The activity supervisor is shutting down.")
            self._pending.append(spec)
            self._submitted_count += 1
            queue_depth = len(self._pending)
            self._condition.notify_all()
        print(f"[INFO] TASK_QUEUED {spec.label} queue_depth={queue_depth}")
        return spec.label

    def wait_for_result(self, label: str) -> Dict[str, Any]:
        """Wait until one submitted activity finishes or the run aborts."""

        with self._condition:
            while label not in self._results:
                if self._abort_requested:
                    return {
                        "task": label,
                        "success": False,
                        "reason": "supervisor_aborted",
                    }
                self._condition.wait(timeout=0.25)
            return dict(self._results[label])

    def close_and_wait(self) -> List[Dict[str, Any]]:
        """Stop accepting work, drain the queue, and return all failures."""

        with self._condition:
            self._accepting = False
            self._condition.notify_all()
        self._thread.join()
        return self.failures

    def abort(self) -> None:
        """Cancel queued work and terminate active children."""

        with self._condition:
            self._accepting = False
            self._abort_requested = True
            while self._pending:
                spec = self._pending.popleft()
                failure = {
                    "task": spec.label,
                    "reason": "cancelled_before_start",
                }
                self._failures.append(failure)
                self._results[spec.label] = {**failure, "success": False}
            self._condition.notify_all()
        # Each active process may consume one TERM grace period and one KILL
        # grace period. The supervisor stops them sequentially while holding
        # its state lock, so budget for the configured concurrency instead of
        # returning early with cleanup still in progress.
        shutdown_timeout = (
            2
            * self.terminate_grace_seconds
            * self.max_concurrent
            + 5
        )
        self._thread.join(timeout=shutdown_timeout)
        if self._thread.is_alive():
            print(
                "[ERROR] TASK_SUPERVISOR_SHUTDOWN_TIMEOUT "
                f"timeout_seconds={shutdown_timeout}"
            )

    def _start_pending_tasks(self) -> None:
        while self._pending and len(self._active) < self.max_concurrent:
            spec = self._pending.popleft()
            process = self._context.Process(
                target=_execute_task_spec,
                args=(spec,),
                name=(
                    f"chimera-{spec.member_id}-w{spec.week}-"
                    f"{spec.date}-{spec.event_index}"
                ),
            )
            try:
                process.start()
            except Exception as exc:
                failure = {
                    "task": spec.label,
                    "reason": "process_start_failed",
                    "error": repr(exc),
                }
                self._failures.append(failure)
                self._results[spec.label] = {
                    **failure,
                    "success": False,
                }
                self._condition.notify_all()
                print(f"[ERROR] TASK_PROCESS_START_FAILED {spec.label}: {exc}")
                continue

            assert process.pid is not None
            self._active[process.pid] = _ActiveTask(
                spec=spec,
                process=process,
                started_monotonic=time.monotonic(),
            )
            print(
                f"[INFO] TASK_PROCESS_STARTED {spec.label} pid={process.pid} "
                f"active={len(self._active)}/{self.max_concurrent}"
            )

    def _finish_process(
        self,
        pid: int,
        active: _ActiveTask,
        *,
        timed_out: bool = False,
        aborted: bool = False,
    ) -> None:
        process = active.process
        process.join(timeout=0)
        exit_code = process.exitcode
        self._active.pop(pid, None)
        self._completed_count += 1

        if aborted:
            failure = {
                "task": active.spec.label,
                "reason": "cancelled_during_shutdown",
            }
            self._failures.append(failure)
            self._results[active.spec.label] = {
                **failure,
                "success": False,
            }
            print(f"[INFO] TASK_CANCELLED {active.spec.label}")
        elif timed_out:
            failure = {
                "task": active.spec.label,
                "reason": "timeout",
                "timeout_seconds": self.timeout_seconds,
            }
            self._failures.append(failure)
            self._results[active.spec.label] = {
                **failure,
                "success": False,
            }
            print(
                f"[ERROR] TASK_TIMEOUT {active.spec.label} "
                f"timeout_seconds={self.timeout_seconds}"
            )
        elif exit_code != 0:
            failure = {
                "task": active.spec.label,
                "reason": "nonzero_exit",
                "exit_code": exit_code,
            }
            self._failures.append(failure)
            self._results[active.spec.label] = {
                **failure,
                "success": False,
            }
            print(
                f"[ERROR] TASK_PROCESS_FAILED {active.spec.label} "
                f"exit_code={exit_code}"
            )
        else:
            self._results[active.spec.label] = {
                "task": active.spec.label,
                "success": True,
                "reason": "completed",
                "exit_code": exit_code,
            }
            print(f"[INFO] TASK_PROCESS_COMPLETE {active.spec.label}")
        self._condition.notify_all()

    def _terminate_active(
        self, pid: int, active: _ActiveTask, *, aborted: bool = False
    ) -> None:
        process = active.process
        if process.is_alive():
            try:
                os.killpg(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                process.terminate()
            process.join(timeout=self.terminate_grace_seconds)
        if process.is_alive():
            try:
                os.killpg(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.join(timeout=self.terminate_grace_seconds)
        self._finish_process(pid, active, timed_out=not aborted, aborted=aborted)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._abort_requested:
                    for pid, active in list(self._active.items()):
                        self._terminate_active(pid, active, aborted=True)
                    return

                self._start_pending_tasks()
                now = time.monotonic()
                for pid, active in list(self._active.items()):
                    if not active.process.is_alive():
                        self._finish_process(pid, active)
                        continue
                    if now - active.started_monotonic > self.timeout_seconds:
                        self._terminate_active(pid, active)

                if (
                    not self._accepting
                    and not self._pending
                    and not self._active
                ):
                    return

                self._condition.wait(timeout=0.25)


def task_supervisor_metadata(supervisor: TaskSupervisor) -> Dict[str, Any]:
    """Return stable counters suitable for run_metadata.jsonl."""

    return {
        "task_submitted": supervisor.submitted_count,
        "task_completed": supervisor.completed_count,
        "task_failures": supervisor.failures,
        "max_concurrent_tasks": supervisor.max_concurrent,
        "task_timeout_seconds": supervisor.timeout_seconds,
        "supervisor_pid": os.getpid(),
    }


def task_artifact_evidence(
    log_dir: str, member_id: str, event_index: int, output_dir: str
) -> List[Dict[str, Any]]:
    """Load and verify artifacts recorded by one successful task transcript."""

    transcript_path = os.path.join(log_dir, "task_transcripts.jsonl")
    if not os.path.isfile(transcript_path):
        return []
    matching_record: Dict[str, Any] | None = None
    with open(transcript_path, "r", encoding="utf-8") as transcript_file:
        for line in transcript_file:
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                record.get("member_id") == member_id
                and record.get("event_index") == event_index
                and record.get("status") == "success"
            ):
                matching_record = record
    if matching_record is None:
        return []

    required_artifact = matching_record.get("required_artifact")
    if not isinstance(required_artifact, str) or not required_artifact:
        return []
    verified_paths = {
        item.get("path")
        for item in matching_record.get("artifact_verification", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("size_bytes"), int)
        and item["size_bytes"] > 0
    }
    if required_artifact not in verified_paths:
        return []

    output_root = os.path.realpath(output_dir)
    evidence: List[Dict[str, Any]] = []
    for relative_path in [required_artifact]:
        artifact_path = os.path.realpath(
            os.path.join(output_root, relative_path)
        )
        if os.path.commonpath([output_root, artifact_path]) != output_root:
            continue
        if not os.path.isfile(artifact_path):
            continue
        size = os.path.getsize(artifact_path)
        if size <= 0:
            continue
        evidence.append({"path": relative_path, "size_bytes": size})
    return evidence
