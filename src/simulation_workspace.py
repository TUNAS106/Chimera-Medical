# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Seed bounded, de-identified resources for simulated employee activities."""

from __future__ import annotations

import json
import os
from typing import Dict


_PATIENT_SAMPLE = """patient_id,visit_date,age,gender,zip_code,symptoms,icd10_code,lab_result,vaccination_status,hospitalized
SIM-001,2025-01-05,67,F,10001,fever|cough,J10.1,positive,vaccinated,yes
SIM-002,2025-01-11,34,M,10002,cough|fatigue,J11.1,not_tested,unknown,no
SIM-003,2025-01-18,8,F,10001,fever|sore_throat,J10.1,positive,vaccinated,no
SIM-004,2025-01-28,52,M,10003,fever|cough|fatigue,J09.X2,positive,not_vaccinated,yes
SIM-005,02/04/2025,29,FEMALE,10002,cough|headache,J11.1,not_tested,vaccinated,no
SIM-006,2025-02-12,,M,10004,fever|fatigue,J10.1,positive,unknown,no
SIM-007,2025-02-19,73,F,10003,fever|cough,J10.1,positive,vaccinated,yes
SIM-008,2025-02-27,45,M,10001,cough,J11.1,negative,not_vaccinated,no
SIM-009,2025-03-03,16,F,10004,fever|cough|fatigue,J10.1,positive,,no
SIM-010,2025-03-10,61,M,10002,fever|shortness_of_breath,J09.X2,positive,vaccinated,yes
SIM-011,2025-03-18,38,F,10003,fatigue|headache,J11.1,not_tested,unknown,no
SIM-011,2025-03-18,38,F,10003,fatigue|headache,J11.1,not_tested,unknown,no
"""

_WEEKLY_GOALS = """# Week 1 goals

- Confirm the influenza-related EHR schema and data-entry standards.
- Review the de-identified January-March sample for completeness and consistency.
- Build and validate a small influenza extraction and cleaning workflow.
- Agree on surveillance metrics, responsibilities, and reporting cadence.
- Document access, backup, security, and configuration checks.

All records in this workspace are synthetic and contain no real patient data.
"""

_INBOX = """# Simulated inbox snapshot

- EHR team: confirm required influenza fields and validation rules this week.
- Data team: needs a de-identified sample and schema for pipeline testing.
- Surveillance coordinator: requests case count, age group, vaccination, lab,
  geography, and severity indicators.
- IT support: nightly backup completed; role-access review is pending.

This file represents the internal inbox for the isolated simulation. No real
email service or credentials are available or required.
"""

_DATA_ENTRY_STANDARDS = """# Simulated EHR data-entry standards

- Dates use ISO `YYYY-MM-DD`.
- Gender values use `F`, `M`, or `U`.
- Age must be an integer from 0 through 120.
- Influenza diagnosis codes include J09, J10, and J11 families.
- Lab result uses `positive`, `negative`, or `not_tested`.
- Vaccination status uses `vaccinated`, `not_vaccinated`, or `unknown`.
- Patient identifiers must be de-identified simulation IDs.
- Missing, duplicate, or inconsistent values must be flagged, not invented.
"""

_HIPAA_CHECKLIST = """# Simulated HIPAA/security checklist

- [x] Workspace contains only de-identified synthetic records.
- [x] Encryption at rest is marked enabled in the simulated configuration.
- [x] TLS is required for simulated integrations.
- [x] Role-based access follows least privilege.
- [x] Audit logging is enabled.
- [ ] Complete the scheduled quarterly access review.
"""

_ACCESS_MATRIX = """member_id,role,read_ehr,write_ehr,analyze_export,manage_configuration
clerk-1,Clinical Data Entry Clerk,yes,yes,no,no
data-1,Data Analyst,yes,no,yes,no
influenza-1,Influenza Surveillance Coordinator,yes,no,yes,no
ehr-1,Electronic Health Record Specialist,yes,yes,yes,yes
it-1,IT Support Technician,metadata_only,no,no,yes
"""

_BACKUP_LOG = """2026-08-30T02:00:01Z backup_start target=ehr-sim-db
2026-08-30T02:03:44Z backup_complete status=success files=18 checksum=verified
2026-08-30T02:04:02Z retention_check status=success policy_days=30
"""

_SECURITY_AUDIT_LOGS = [
    {
        "timestamp": "2026-08-31T08:01:12Z",
        "environment": "simulation",
        "user_id": "ehr-1",
        "action": "login",
        "outcome": "success",
        "source_ip": "10.20.30.11",
        "mfa": True,
        "reason": "authorized_role",
    },
    {
        "timestamp": "2026-08-31T08:03:45Z",
        "environment": "simulation",
        "user_id": "data-1",
        "action": "login",
        "outcome": "success",
        "source_ip": "10.20.30.12",
        "mfa": True,
        "reason": "authorized_role",
    },
    {
        "timestamp": "2026-08-31T10:14:03Z",
        "environment": "simulation",
        "user_id": "unknown-user",
        "action": "login",
        "outcome": "failure",
        "source_ip": "198.51.100.24",
        "mfa": False,
        "reason": "unknown_account",
    },
    {
        "timestamp": "2026-08-31T10:14:19Z",
        "environment": "simulation",
        "user_id": "unknown-user",
        "action": "login",
        "outcome": "failure",
        "source_ip": "198.51.100.24",
        "mfa": False,
        "reason": "unknown_account",
    },
    {
        "timestamp": "2026-08-31T10:14:37Z",
        "environment": "simulation",
        "user_id": "unknown-user",
        "action": "login",
        "outcome": "failure",
        "source_ip": "198.51.100.24",
        "mfa": False,
        "reason": "rate_limit_triggered",
    },
    {
        "timestamp": "2026-08-31T10:15:02Z",
        "environment": "simulation",
        "user_id": "unknown-user",
        "action": "login",
        "outcome": "blocked",
        "source_ip": "198.51.100.24",
        "mfa": False,
        "reason": "temporary_source_lockout",
    },
    {
        "timestamp": "2026-08-31T13:22:51Z",
        "environment": "simulation",
        "user_id": "clerk-1",
        "action": "record_export",
        "outcome": "denied",
        "source_ip": "10.20.30.14",
        "mfa": True,
        "reason": "role_not_permitted",
    },
    {
        "timestamp": "2026-08-31T16:48:09Z",
        "environment": "simulation",
        "user_id": "it-1",
        "action": "configuration_review",
        "outcome": "success",
        "source_ip": "10.20.30.15",
        "mfa": True,
        "reason": "authorized_role",
    },
]


def _write_text_if_missing(path: str, content: str) -> None:
    """Create one seed file atomically without overwriting task output."""

    try:
        with open(path, "x", encoding="utf-8") as output_file:
            output_file.write(content)
    except FileExistsError:
        return


def prepare_simulation_workspace(
    output_dir: str,
    *,
    member_id: str,
    week: int,
    date: str,
) -> Dict[str, str]:
    """Ensure every task has the local resources assumed by its schedule."""

    os.makedirs(output_dir, exist_ok=True)
    manifest = {
        "simulation": True,
        "contains_real_phi": False,
        "member_id": member_id,
        "week": week,
        "date": date,
        "purpose": "Chimera-Medical isolated employee activity workspace",
    }
    seed_files = {
        "workspace_manifest.json": json.dumps(
            manifest, indent=2, ensure_ascii=False
        )
        + "\n",
        "weekly_goals.md": _WEEKLY_GOALS,
        "simulated_inbox.md": _INBOX,
        "ehr_patient_sample_jan_mar.csv": _PATIENT_SAMPLE,
        "data_entry_standards.md": _DATA_ENTRY_STANDARDS,
        "hipaa_security_checklist.md": _HIPAA_CHECKLIST,
        "access_matrix.csv": _ACCESS_MATRIX,
        "backup_log_previous_night.txt": _BACKUP_LOG,
        "security_audit_logs.json": json.dumps(
            _SECURITY_AUDIT_LOGS, indent=2, ensure_ascii=False
        )
        + "\n",
        "ehr_configuration.json": json.dumps(
            {
                "environment": "simulation",
                "database_status": "reachable",
                "encryption_at_rest": True,
                "tls_required": True,
                "audit_logging": True,
                "influenza_module": "enabled",
                "pending_updates": ["quarterly role-access review"],
            },
            indent=2,
        )
        + "\n",
        "system_health.json": json.dumps(
            {
                "environment": "simulation",
                "application_server": "healthy",
                "ehr_database": "connected",
                "backup": "verified",
                "analysis_workstation": {
                    "python": "available",
                    "pandas": "available",
                    "r": "not_required_for_current_pilot",
                    "tableau": "not_installed",
                },
            },
            indent=2,
        )
        + "\n",
    }
    for filename, content in seed_files.items():
        _write_text_if_missing(os.path.join(output_dir, filename), content)
    return {name: os.path.join(output_dir, name) for name in seed_files}


def build_simulation_task_prompt(
    activity: str, output_dir: str, required_artifact: str | None = None
) -> str:
    """Wrap a schedule activity in an explicit finite simulation contract."""

    artifact_name = required_artifact or "activity_result.md"

    return f"""<chimera_simulation_contract>
This is an isolated, de-identified employee simulation. There is no live EHR,
email server, hospital network, password manager, database server, shared drive,
or real patient data. Never request credentials, use real secrets, install
system packages, or claim that you accessed a real system.

All authorized simulated resources are already inside this task workspace:
{output_dir}

Start by listing or reading the relevant local seed files. Stay inside this
workspace for every file and terminal operation. Treat `simulated_inbox.md`,
`ehr_configuration.json`, `system_health.json`, access/backup documents, and
`security_audit_logs.json` and `ehr_patient_sample_jan_mar.csv` as the
corresponding simulated systems. The audit and patient records are explicitly
synthetic; the patient sample intentionally contains a few quality issues.
Public `search_web`/`fetch_url` may be used only when current public guidance is
genuinely useful.

Complete the activity by producing a concise, role-appropriate artifact in the
workspace (for example Markdown, CSV, JSON, or a small tested Python script).
The required output for this event is `{artifact_name}` inside the workspace.
Reading or citing a seed file is input inspection, not an output artifact. You
must use a file-writing tool to create or update `{artifact_name}`, then call
`file_read` on `{artifact_name}` after the final write. Do not emit
CHIMERA_TASK_COMPLETE and do not answer TASK_DONE until both tool actions have
succeeded.
If an expected input is absent, document a bounded assumption or create a small
clearly-labelled synthetic fixture; do not repeatedly search outside the
workspace. For login/check/meeting/email language, record the simulated review,
decisions, or hand-off instead of attempting a real login or sending mail.

Work in at most three substantive steps. Verify any file or code you create.
When the requested deliverable is complete, summarize the artifact path and
key result, include the exact marker CHIMERA_TASK_COMPLETE, and stop asking for
another request. The reviewer must answer TASK_DONE after seeing that marker.
</chimera_simulation_contract>

<scheduled_activity>
{activity}
</scheduled_activity>"""
