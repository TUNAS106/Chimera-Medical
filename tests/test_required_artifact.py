import unittest

from task import _required_artifact_is_verified


class RequiredArtifactTests(unittest.TestCase):
    def test_exact_nonempty_required_artifact_is_accepted(self):
        self.assertTrue(
            _required_artifact_is_verified(
                "activity_event_21.md",
                [{"path": "activity_event_21.md", "size_bytes": 12}],
            )
        )

    def test_unrelated_verified_artifact_is_rejected(self):
        self.assertFalse(
            _required_artifact_is_verified(
                "activity_event_21.md",
                [{"path": "backup.json", "size_bytes": 218}],
            )
        )

    def test_empty_required_artifact_is_rejected(self):
        self.assertFalse(
            _required_artifact_is_verified(
                "activity_event_21.md",
                [{"path": "activity_event_21.md", "size_bytes": 0}],
            )
        )


if __name__ == "__main__":
    unittest.main()
