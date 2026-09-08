import json
import os
import tempfile
import unittest

from simulation_workspace import prepare_simulation_workspace


class SimulationWorkspaceTests(unittest.TestCase):
    def test_security_audit_seed_is_synthetic_and_actionable(self):
        with tempfile.TemporaryDirectory() as output_dir:
            seeds = prepare_simulation_workspace(
                output_dir,
                member_id="it-1",
                week=1,
                date="Wednesday",
            )

            audit_path = seeds["security_audit_logs.json"]
            self.assertTrue(os.path.isfile(audit_path))
            with open(audit_path, encoding="utf-8") as audit_file:
                records = json.load(audit_file)

        self.assertTrue(records)
        self.assertTrue(
            all(record["environment"] == "simulation" for record in records)
        )
        self.assertTrue(
            any(record["outcome"] == "failure" for record in records)
        )
        self.assertTrue(
            any(record["outcome"] == "blocked" for record in records)
        )


if __name__ == "__main__":
    unittest.main()
