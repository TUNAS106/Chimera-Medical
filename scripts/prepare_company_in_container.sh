#!/usr/bin/env bash
# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
STATUS_ONLY=false

if [[ "${1:-}" == "--status-only" ]]; then
    STATUS_ONLY=true
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--status-only]" >&2
    exit 2
fi

cd "$REPO_DIR"
source "$REPO_DIR/.venv/bin/activate"
if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

status() {
    python "$REPO_DIR/src/company_preparation_status.py" "$@"
}

if [[ "$STATUS_ONLY" == "true" ]]; then
    status --phase all
    exit $?
fi

echo "Checking dependencies, configuration, and API..."
uv pip check
python -c \
    'import config; print(f"scenario={config.scenario_name} employees={config.employee_number} weeks={config.period}"); assert config.employee_number == 5, "CHIMERA_EMPLOYEE_NUMBER must be 5 for this run"'
python -c \
    'import config; from openai import OpenAI; models=OpenAI(base_url=config.foundation_base_url, api_key=config.foundation_api_key, timeout=60, max_retries=0).models.list(); ids=[model.id for model in models.data]; print(f"available_models={ids}"); assert config.foundation_model in ids, f"Configured model {config.foundation_model} is unavailable"'

run_phase() {
    local phase="$1"
    local phase_script="$2"

    if status --phase "$phase" --quiet; then
        echo "[SKIP] $phase is already valid."
        return
    fi

    echo "======= Building $phase with $phase_script ======="
    python "$REPO_DIR/src/$phase_script"
    status --phase "$phase"
}

run_phase company company_profile_automation.py
run_phase profiles profile_generation.py
run_phase meeting meeting_for_weekly_goal_auto.py
run_phase weekly_schedules post_meeting_summary_auto.py
run_phase daily_schedules daily_plan_generation_auto.py

echo "======= Final preparation validation ======="
status --phase all
echo "Company preparation is complete. Employee behavior and SCAP/PCAP capture have not started."
