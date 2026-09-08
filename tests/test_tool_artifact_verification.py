import os
import tempfile
import unittest
from types import SimpleNamespace

from owl.utils.enhanced_role_playing import (
    _artifact_path_is_required,
    _artifact_tool_call_succeeded,
    _paths_refer_to_same_file,
    run_chimera_society,
)


class _FakeToolCall:
    def __init__(self, record):
        self.record = record

    def as_dict(self):
        return self.record


def _response(content, tool_records=None):
    message = SimpleNamespace(content=content)
    info = {
        "tool_calls": [
            _FakeToolCall(record) for record in (tool_records or [])
        ]
    }
    return SimpleNamespace(
        info=info,
        msg=message,
        msgs=[message],
        terminated=False,
    )


class _FakeSociety:
    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.init_prompt = None

    def init_chat(self, prompt):
        self.init_prompt = prompt
        return SimpleNamespace(content=prompt)

    def step(self, _input_msg):
        return next(self.rounds)


class ToolArtifactVerificationTests(unittest.TestCase):
    def test_relative_write_matches_absolute_read(self):
        filename = "activity_ehr-1_week_1_Monday_event_3_attempt_2.md"
        absolute_path = os.path.join("/data/Chimera/workspace", filename)

        self.assertTrue(_paths_refer_to_same_file(filename, absolute_path))

    def test_different_file_does_not_match(self):
        self.assertFalse(
            _paths_refer_to_same_file(
                "activity_event_2.md",
                "/data/Chimera/workspace/activity_event_3.md",
            )
        )

    def test_different_absolute_directories_do_not_match(self):
        self.assertFalse(
            _paths_refer_to_same_file(
                "/data/Chimera/workspace-a/report.md",
                "/data/Chimera/workspace-b/report.md",
            )
        )

    def test_file_read_content_may_contain_failure_language(self):
        content = 'print("Failed to read the input CSV file.")'

        self.assertTrue(
            _artifact_tool_call_succeeded("file_read", content)
        )

    def test_file_read_tool_error_is_rejected(self):
        self.assertFalse(
            _artifact_tool_call_succeeded(
                "file_read",
                "File not found or not a regular file: /tmp/missing.json",
            )
        )

    def test_write_requires_explicit_success_envelope(self):
        self.assertTrue(
            _artifact_tool_call_succeeded(
                "write_file",
                "Content successfully written to file: /tmp/report.md",
            )
        )
        self.assertFalse(
            _artifact_tool_call_succeeded(
                "write_file",
                "Error occurred while writing to file /tmp/report.md: full",
            )
        )

    def test_auxiliary_artifact_does_not_match_required_artifact(self):
        self.assertFalse(
            _artifact_path_is_required(
                "daily_influenza_export.py",
                "activity_it-1_week_1_Wednesday_event_18_attempt_2.md",
            )
        )

    def test_absolute_required_artifact_path_matches_filename(self):
        self.assertTrue(
            _artifact_path_is_required(
                "/data/Chimera/workspace/activity_event_18.md",
                "activity_event_18.md",
            )
        )

    def test_auxiliary_write_read_cannot_complete_required_artifact(self):
        auxiliary = "/data/Chimera/workspace/daily_export.py"
        required = "activity_it-1_week_1_Wednesday_event_18_attempt_2.md"
        tool_records = [
            {
                "tool_name": "write_file",
                "args": {"path": auxiliary},
                "result": f"Content successfully written to file: {auxiliary}",
            },
            {
                "tool_name": "file_read",
                "args": {"path": auxiliary},
                "result": "print('export')",
            },
        ]
        society = _FakeSociety(
            [
                (
                    _response("CHIMERA_TASK_COMPLETE", tool_records),
                    _response("Instruction: create the script"),
                ),
                (
                    _response("CHIMERA_TASK_COMPLETE"),
                    _response("TASK_DONE"),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as log_dir:
            _, _, token_info = run_chimera_society(
                society,
                round_limit=2,
                log_dir=log_dir,
                required_artifact=required,
            )

        self.assertIn(required, society.init_prompt)
        self.assertFalse(token_info["artifact_tool_verified"])
        self.assertFalse(token_info["completion_signal"])

    def test_required_write_read_allows_task_done(self):
        required = "activity_it-1_week_1_Wednesday_event_18_attempt_2.md"
        absolute = f"/data/Chimera/workspace/{required}"
        tool_records = [
            {
                "tool_name": "write_file",
                "args": {"path": absolute},
                "result": f"Content successfully written to file: {absolute}",
            },
            {
                "tool_name": "file_read",
                "args": {"path": absolute},
                "result": "# Verified export script",
            },
        ]
        society = _FakeSociety(
            [
                (
                    _response("CHIMERA_TASK_COMPLETE", tool_records),
                    _response("Instruction: create the required artifact"),
                ),
                (
                    _response("CHIMERA_TASK_COMPLETE"),
                    _response("TASK_DONE"),
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as log_dir:
            _, _, token_info = run_chimera_society(
                society,
                round_limit=2,
                log_dir=log_dir,
                required_artifact=required,
            )

        self.assertTrue(token_info["artifact_tool_verified"])
        self.assertTrue(token_info["completion_signal"])
        self.assertEqual(token_info["termination_reason"], "task_done")


if __name__ == "__main__":
    unittest.main()
