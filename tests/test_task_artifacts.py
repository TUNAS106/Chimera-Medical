import json
import os
import tempfile
import unittest

from task_supervisor import task_artifact_evidence


class TaskArtifactEvidenceTests(unittest.TestCase):
    def test_only_existing_nonempty_transcript_artifacts_are_returned(self):
        with tempfile.TemporaryDirectory() as root:
            log_dir = os.path.join(root, "logs")
            output_dir = os.path.join(root, "workspace")
            os.makedirs(log_dir)
            os.makedirs(output_dir)
            with open(
                os.path.join(output_dir, "report.md"), "w", encoding="utf-8"
            ) as report:
                report.write("verified")
            with open(
                os.path.join(output_dir, "empty.md"), "w", encoding="utf-8"
            ):
                pass
            record = {
                "status": "success",
                "member_id": "data-1",
                "event_index": 3,
                "required_artifact": "report.md",
                "changed_artifacts": ["report.md", "empty.md", "missing.md"],
                "artifact_verification": [
                    {"path": "report.md", "size_bytes": 8},
                    {"path": "empty.md", "size_bytes": 0},
                ],
            }
            with open(
                os.path.join(log_dir, "task_transcripts.jsonl"),
                "w",
                encoding="utf-8",
            ) as transcript:
                transcript.write(json.dumps(record) + "\n")
            evidence = task_artifact_evidence(
                log_dir, "data-1", 3, output_dir
            )
            self.assertEqual(evidence, [{"path": "report.md", "size_bytes": 8}])

    def test_unrelated_artifact_cannot_satisfy_required_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            log_dir = os.path.join(root, "logs")
            output_dir = os.path.join(root, "workspace")
            os.makedirs(log_dir)
            os.makedirs(output_dir)
            with open(
                os.path.join(output_dir, "backup.json"),
                "w",
                encoding="utf-8",
            ) as backup:
                backup.write("verified backup")
            record = {
                "status": "success",
                "member_id": "ehr-1",
                "event_index": 21,
                "required_artifact": "activity_event_21.md",
                "changed_artifacts": ["backup.json"],
                "artifact_verification": [
                    {"path": "backup.json", "size_bytes": 15}
                ],
            }
            with open(
                os.path.join(log_dir, "task_transcripts.jsonl"),
                "w",
                encoding="utf-8",
            ) as transcript:
                transcript.write(json.dumps(record) + "\n")

            self.assertEqual(
                task_artifact_evidence(
                    log_dir, "ehr-1", 21, output_dir
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
