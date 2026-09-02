import os
import unittest

from owl.utils.enhanced_role_playing import _paths_refer_to_same_file


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


if __name__ == "__main__":
    unittest.main()
