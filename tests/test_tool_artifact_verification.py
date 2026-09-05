import os
import unittest

from owl.utils.enhanced_role_playing import (
    _artifact_tool_call_succeeded,
    _paths_refer_to_same_file,
)


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


if __name__ == "__main__":
    unittest.main()
