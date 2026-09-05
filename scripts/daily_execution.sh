#!/usr/bin/env bash
# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Load orchestration settings such as CHIMERA_PERIOD without printing secrets.
if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

if (( EUID != 0 )); then
    echo "This capture runner must be executed on the Docker host as root." >&2
    echo "Run: sudo bash scripts/daily_execution.sh" >&2
    exit 1
fi

CONTAINER_NAME="${CHIMERA_CONTAINER_NAME:-chimera2}"
OUTPUT_DIR="${CHIMERA_CAPTURE_DIR:-/data/Logs}"
SYSDIG_PLUGIN_DIR="${CHIMERA_SYSDIG_PLUGIN_DIR:-/usr/share/sysdig/plugins}"

resolve_sysdig_bin() {
    if [[ -n "${CHIMERA_SYSDIG_BIN:-}" ]]; then
        printf '%s\n' "$CHIMERA_SYSDIG_BIN"
        return
    fi

    if command -v sysdig-chimera >/dev/null 2>&1; then
        command -v sysdig-chimera
        return
    fi

    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        local invoking_home
        invoking_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
        if [[ -x "$invoking_home/.local/bin/sysdig-chimera" ]]; then
            printf '%s\n' "$invoking_home/.local/bin/sysdig-chimera"
            return
        fi
    fi

    echo "Patched Sysdig was not found." >&2
    echo "Set CHIMERA_SYSDIG_BIN to the sysdig-chimera executable." >&2
    return 1
}

for required_command in awk docker tmux nsenter tcpdump stat mktemp flock timeout; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Required host command is missing: $required_command" >&2
        exit 1
    fi
done

# Only one host runner may manage a container at a time. Without this lock, a
# second invocation can archive capture files that the first invocation still
# has open, leaving Sysdig writing under a previous_* path.
RUNNER_LOCK_FILE="/run/lock/chimera-daily-${CONTAINER_NAME}.lock"
exec 9>"$RUNNER_LOCK_FILE"
if ! flock -n 9; then
    echo "Another daily_execution.sh runner is already active for $CONTAINER_NAME." >&2
    echo "Wait for it to finish or stop it before starting another run." >&2
    exit 1
fi

SYSDIG_BIN="$(resolve_sysdig_bin)"
if [[ ! -x "$SYSDIG_BIN" ]]; then
    echo "Patched Sysdig is not executable: $SYSDIG_BIN" >&2
    exit 1
fi
if [[ ! -f "$SYSDIG_PLUGIN_DIR/libcontainer.so" ]]; then
    echo "Sysdig container plugin is missing: $SYSDIG_PLUGIN_DIR/libcontainer.so" >&2
    exit 1
fi

if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "Container $CONTAINER_NAME does not exist." >&2
    exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]]; then
    echo "Container $CONTAINER_NAME is not running." >&2
    exit 1
fi

HOST_MIN_AVAILABLE_MB="${CHIMERA_HOST_MIN_AVAILABLE_MB:-2048}"
if ! [[ "$HOST_MIN_AVAILABLE_MB" =~ ^[1-9][0-9]*$ ]]; then
    echo "CHIMERA_HOST_MIN_AVAILABLE_MB must be a positive integer." >&2
    exit 1
fi
check_host_memory() {
    local available_kb
    available_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    if [[ -z "$available_kb" ]] || \
       (( available_kb < HOST_MIN_AVAILABLE_MB * 1024 )); then
        echo "Host memory is below the ${HOST_MIN_AVAILABLE_MB} MiB safety floor; capture was not started." >&2
        return 1
    fi
    echo "Host memory preflight: available=$((available_kb / 1024)) MiB floor=${HOST_MIN_AVAILABLE_MB} MiB."
}
check_host_memory

if ! docker exec "$CONTAINER_NAME" bash -lc \
    'source /data/Chimera/.venv/bin/activate && PYTHONPATH=/data/Chimera/src python /data/Chimera/src/sanitize_model_audit.py'; then
    echo "Unable to sanitize the existing model audit; capture was not started." >&2
    exit 1
fi

if ! docker exec "$CONTAINER_NAME" bash -lc \
    'source /data/Chimera/.venv/bin/activate && PYTHONPATH=/data/Chimera/src python /data/Chimera/src/model_preflight.py'; then
    echo "Model preflight failed. Refresh the Kaggle session/proxy URL in .env; capture was not started." >&2
    exit 1
fi

check_chromium() {
    docker exec "$CONTAINER_NAME" bash -lc \
        'source /data/Chimera/.venv/bin/activate && python -c '"'"'from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop()'"'"''
}

WEB_MODE="${CHIMERA_WEB_MODE:-search_only}"
case "$WEB_MODE" in
    llm_only)
        echo "Web mode: llm_only (no public search/browser preflight)."
        ;;
    search_only)
        echo "Web mode: search_only (bounded HTTP search/fetch, no Chromium)."
        if ! docker exec "$CONTAINER_NAME" bash -lc \
            'source /data/Chimera/.venv/bin/activate && PYTHONPATH=/data/Chimera/src python /data/Chimera/src/web_search_preflight.py'; then
            echo "Web search preflight failed; capture and simulation were not started." >&2
            exit 1
        fi
        ;;
    browser)
        echo "Web mode: browser (Playwright enabled)."
        # Install once before capture.  Worker processes must never race for an
        # apt lock or download Chromium during the simulated day.
        if ! check_chromium >/dev/null 2>&1; then
            echo "Chromium is not ready; installing Playwright dependencies once..."
            docker exec "$CONTAINER_NAME" bash -lc \
                'source /data/Chimera/.venv/bin/activate && python -m playwright install-deps chromium && python -m playwright install chromium'
            if ! check_chromium >/dev/null 2>&1; then
                echo "Chromium preflight failed after installation." >&2
                exit 1
            fi
        fi
        echo "Chromium preflight passed."
        if ! docker exec "$CONTAINER_NAME" bash -lc \
            'source /data/Chimera/.venv/bin/activate && PYTHONPATH=/data/Chimera/src python /data/Chimera/src/web_search_preflight.py'; then
            echo "Web search preflight failed; capture and simulation were not started." >&2
            exit 1
        fi
        ;;
    *)
        echo "Invalid CHIMERA_WEB_MODE=$WEB_MODE (use llm_only, search_only, or browser)." >&2
        exit 1
        ;;
esac

MAX_CONCURRENT_TASKS="${CHIMERA_MAX_CONCURRENT_TASKS:-3}"
MAX_AUX_MODEL_CALLS="${CHIMERA_MAX_AUX_MODEL_CALLS:-1}"
VLLM_MAX_NUM_SEQS="${CHIMERA_VLLM_MAX_NUM_SEQS:-4}"
TASK_TIMEOUT_SECONDS="${CHIMERA_TASK_TIMEOUT_SECONDS:-900}"
if ! [[ "$MAX_CONCURRENT_TASKS" =~ ^[1-9][0-9]*$ ]]; then
    echo "CHIMERA_MAX_CONCURRENT_TASKS must be a positive integer." >&2
    exit 1
fi
if ! [[ "$MAX_AUX_MODEL_CALLS" =~ ^[1-9][0-9]*$ ]]; then
    echo "CHIMERA_MAX_AUX_MODEL_CALLS must be a positive integer." >&2
    exit 1
fi
if ! [[ "$VLLM_MAX_NUM_SEQS" =~ ^[1-9][0-9]*$ ]]; then
    echo "CHIMERA_VLLM_MAX_NUM_SEQS must be a positive integer." >&2
    exit 1
fi
if (( MAX_CONCURRENT_TASKS + MAX_AUX_MODEL_CALLS > VLLM_MAX_NUM_SEQS )); then
    echo "Activity + auxiliary concurrency exceeds vLLM max_num_seqs=$VLLM_MAX_NUM_SEQS." >&2
    exit 1
fi
if [[ "$WEB_MODE" == "browser" ]] && (( MAX_CONCURRENT_TASKS > 2 )); then
    echo "Browser mode is capped at 2 activity workers on this 16 GiB host." >&2
    echo "Set CHIMERA_MAX_CONCURRENT_TASKS=2 before using browser mode." >&2
    exit 1
fi
if ! [[ "$TASK_TIMEOUT_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "CHIMERA_TASK_TIMEOUT_SECONDS must be numeric." >&2
    exit 1
fi
echo "Activity supervisor: max_concurrent=$MAX_CONCURRENT_TASKS aux=$MAX_AUX_MODEL_CALLS vllm_sequences=$VLLM_MAX_NUM_SEQS timeout=${TASK_TIMEOUT_SECONDS}s."

CONTAINER_PID="$(docker inspect -f '{{.State.Pid}}' "$CONTAINER_NAME")"
CONTAINER_FULL_ID="$(docker inspect -f '{{.Id}}' "$CONTAINER_NAME")"
# The container plugin exposes container.id as the reliable 12-character ID.
# container.full_id depends on asynchronous runtime enrichment.
CONTAINER_ID="${CONTAINER_FULL_ID:0:12}"
# sched_yield dominates the trace but does not describe application behavior.
# Exclude it at capture time so it is never written to new SCAP files.
SCAP_FILTER="container.id=$CONTAINER_ID and evt.type!=sched_yield"

SCAP_SESSION="chimera-scap-$$"
PCAP_SESSION="chimera-pcap-$$"
CAPTURE_STATUS_DIR="$(mktemp -d /tmp/chimera-capture-status.XXXXXX)"
SCAP_EXIT_FILE=""
PCAP_EXIT_FILE=""
CONTAINER_SIM_PID_FILE=""

stop_container_simulation() {
    local pid_file="$1"
    [[ -n "$pid_file" ]] || return 0
    docker exec "$CONTAINER_NAME" bash -lc '
        pid_file="$1"
        [[ -s "$pid_file" ]] || exit 0
        read -r sim_pid < "$pid_file"
        if ! [[ "$sim_pid" =~ ^[1-9][0-9]*$ ]] ||
           [[ ! -r "/proc/$sim_pid/cmdline" ]]; then
            rm -f -- "$pid_file"
            exit 0
        fi
        command_line="$(tr "\0" " " < "/proc/$sim_pid/cmdline")"
        if [[ "$command_line" != *"/data/Chimera/src/daily_execution_auto.py"* ]]; then
            rm -f -- "$pid_file"
            exit 0
        fi
        kill -TERM -- "-$sim_pid" 2>/dev/null || true
        for _ in $(seq 1 15); do
            kill -0 "$sim_pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$sim_pid" 2>/dev/null; then
            kill -KILL -- "-$sim_pid" 2>/dev/null || true
        fi
        rm -f -- "$pid_file"
    ' bash "$pid_file" || true
}

cleanup() {
    stop_container_simulation "$CONTAINER_SIM_PID_FILE"
    if [[ -n "$SCAP_EXIT_FILE" ]]; then
        tmux send-keys -t "$SCAP_SESSION" C-c 2>/dev/null || true
    fi
    if [[ -n "$PCAP_EXIT_FILE" ]]; then
        tmux send-keys -t "$PCAP_SESSION" C-c 2>/dev/null || true
    fi
    if [[ -n "$SCAP_EXIT_FILE" ]]; then
        wait_for_capture_stop "$SCAP_EXIT_FILE" "Sysdig/SCAP" 15 || true
    fi
    if [[ -n "$PCAP_EXIT_FILE" ]]; then
        wait_for_capture_stop "$PCAP_EXIT_FILE" "tcpdump/PCAP" 15 || true
    fi
    tmux kill-session -t "$SCAP_SESSION" 2>/dev/null || true
    tmux kill-session -t "$PCAP_SESSION" 2>/dev/null || true
    if [[ -n "$SCAP_EXIT_FILE" ]]; then
        rm -f -- "$SCAP_EXIT_FILE"
    fi
    if [[ -n "$PCAP_EXIT_FILE" ]]; then
        rm -f -- "$PCAP_EXIT_FILE"
    fi
    rmdir -- "$CAPTURE_STATUS_DIR" 2>/dev/null || true
}
trap cleanup EXIT

tmux new-session -d -s "$SCAP_SESSION"
tmux new-session -d -s "$PCAP_SESSION"

mkdir -p "$OUTPUT_DIR"

wait_for_fresh_capture() {
    local capture_file="$1"
    local started_at="$2"
    local capture_name="$3"
    local runtime_log="$4"
    local timeout_seconds="$5"
    local exit_file="${6:-}"
    local deadline=$((SECONDS + timeout_seconds))

    while (( SECONDS < deadline )); do
        if [[ -n "$exit_file" && -s "$exit_file" ]]; then
            echo "$capture_name exited before becoming ready (status $(<"$exit_file"))." >&2
            if [[ -s "$runtime_log" ]]; then
                tail -n 40 "$runtime_log" >&2
            fi
            return 1
        fi
        if [[ -s "$capture_file" ]] &&
           (( $(stat -c '%Y' "$capture_file") >= started_at )); then
            return 0
        fi
        sleep 1
    done

    echo "$capture_name did not become ready within ${timeout_seconds}s." >&2
    if [[ -s "$runtime_log" ]]; then
        echo "----- $runtime_log -----" >&2
        tail -n 40 "$runtime_log" >&2
    fi
    return 1
}

wait_for_capture_stop() {
    local exit_file="$1"
    local capture_name="$2"
    local timeout_seconds="$3"
    local deadline=$((SECONDS + timeout_seconds))

    while (( SECONDS < deadline )); do
        if [[ -s "$exit_file" ]]; then
            return 0
        fi
        sleep 1
    done

    echo "$capture_name did not stop cleanly within ${timeout_seconds}s." >&2
    return 1
}

# Run the complete configured period and all seven days by default. Override
# with CHIMERA_WEEKS="1" or CHIMERA_DATES="Monday Tuesday" when needed.
read -r -a weeks <<< "${CHIMERA_WEEKS:-$(seq -s ' ' 1 "${CHIMERA_PERIOD:-2}")}"
read -r -a dates <<< "${CHIMERA_DATES:-Monday Tuesday Wednesday Thursday Friday Saturday Sunday}"

for week in "${weeks[@]}"; do
    for date in "${dates[@]}"; do
        echo "======= Running for week $week and date $date ========="
        check_host_memory
        if ! docker exec "$CONTAINER_NAME" bash -lc \
            'source /data/Chimera/.venv/bin/activate && PYTHONPATH=/data/Chimera/src python /data/Chimera/src/daily_run_preflight.py --week "$1" --date "$2"' \
            bash "$week" "$date"; then
            echo "Daily schedule preflight failed; capture was not started." >&2
            exit 1
        fi
        FILE_NAME="week_${week}_${date}"
        SCAP_FILE="$OUTPUT_DIR/$FILE_NAME.scap"
        PCAP_FILE="$OUTPUT_DIR/$FILE_NAME.pcap"
        SYSDIG_RUNTIME_LOG="$OUTPUT_DIR/$FILE_NAME.sysdig.log"
        TCPDUMP_RUNTIME_LOG="$OUTPUT_DIR/$FILE_NAME.tcpdump.log"
        SCAP_EXIT_FILE="$CAPTURE_STATUS_DIR/$FILE_NAME.sysdig.exit"
        PCAP_EXIT_FILE="$CAPTURE_STATUS_DIR/$FILE_NAME.tcpdump.exit"
        rm -f -- "$SCAP_EXIT_FILE" "$PCAP_EXIT_FILE"

        # A retry must never append to or silently overwrite an earlier
        # capture. Move any existing outputs aside on the same filesystem so
        # they remain recoverable and the new writers start from fresh paths.
        capture_outputs=(
            "$SCAP_FILE"
            "$PCAP_FILE"
            "$SYSDIG_RUNTIME_LOG"
            "$TCPDUMP_RUNTIME_LOG"
        )
        existing_capture_outputs=()
        for capture_output in "${capture_outputs[@]}"; do
            if [[ -e "$capture_output" ]]; then
                existing_capture_outputs+=("$capture_output")
            fi
        done
        if (( ${#existing_capture_outputs[@]} > 0 )); then
            PREVIOUS_CAPTURE_DIR="$(
                mktemp -d "$OUTPUT_DIR/previous_${FILE_NAME}.XXXXXX"
            )"
            mv -- "${existing_capture_outputs[@]}" "$PREVIOUS_CAPTURE_DIR/"
            echo "Existing capture outputs archived: $PREVIOUS_CAPTURE_DIR"
        fi
        CAPTURE_STARTED_AT="$(date +%s)"

        # Capture on the host. sysdig-chimera embeds the modern-BPF driver
        # patched for this kernel; the plugin supplies container.id metadata.
        printf -v scap_record_cmd \
            'capture_exit_file=%q; trap '\''capture_interrupted=1'\'' INT TERM; env SYSDIG_PLUGIN_DIR=%q %q --modern-bpf -w %q %q >%q 2>&1; capture_rc=$?; printf "%%s\n" "$capture_rc" >"$capture_exit_file"; trap - INT TERM' \
            "$SCAP_EXIT_FILE" \
            "$SYSDIG_PLUGIN_DIR" \
            "$SYSDIG_BIN" \
            "$SCAP_FILE" \
            "$SCAP_FILTER" \
            "$SYSDIG_RUNTIME_LOG"
        tmux send-keys -t "$SCAP_SESSION" "$scap_record_cmd" Enter

        printf -v pcap_record_cmd \
            'capture_exit_file=%q; trap '\''capture_interrupted=1'\'' INT TERM; nsenter -t %q -n tcpdump -i any -U -w %q >%q 2>&1; capture_rc=$?; printf "%%s\n" "$capture_rc" >"$capture_exit_file"; trap - INT TERM' \
            "$PCAP_EXIT_FILE" \
            "$CONTAINER_PID" \
            "$PCAP_FILE" \
            "$TCPDUMP_RUNTIME_LOG"
        tmux send-keys -t "$PCAP_SESSION" "$pcap_record_cmd" Enter

        # Modern BPF takes several seconds to pass the kernel verifier. Do not
        # start employee behavior until both capture files are freshly opened.
        wait_for_fresh_capture \
            "$SCAP_FILE" "$CAPTURE_STARTED_AT" "Sysdig/SCAP" \
            "$SYSDIG_RUNTIME_LOG" 45 "$SCAP_EXIT_FILE"
        wait_for_fresh_capture \
            "$PCAP_FILE" "$CAPTURE_STARTED_AT" "tcpdump/PCAP" \
            "$TCPDUMP_RUNTIME_LOG" 15 "$PCAP_EXIT_FILE"

        echo "Capture ready: $SCAP_FILE"
        echo "Capture ready: $PCAP_FILE"

        # run the simulation
        CONTAINER_SIM_PID_FILE="/tmp/chimera-daily-$$-${week}-${date}.pid"
        set +e
        docker exec "$CONTAINER_NAME" bash -lc \
            'pid_file="$1"; date_name="$2"; week_number="$3"; printf "%s\n" "$$" > "$pid_file"; source /data/Chimera/.venv/bin/activate && exec python /data/Chimera/src/daily_execution_auto.py --date "$date_name" --week "$week_number"' \
            bash "$CONTAINER_SIM_PID_FILE" "$date" "$week"
        SIMULATION_RC=$?
        set -e
        docker exec "$CONTAINER_NAME" rm -f -- "$CONTAINER_SIM_PID_FILE" \
            >/dev/null 2>&1 || true
        CONTAINER_SIM_PID_FILE=""

        CAPTURE_FAILED=0
        if [[ -s "$SCAP_EXIT_FILE" ]]; then
            echo "Sysdig/SCAP exited before simulation completed (status $(<"$SCAP_EXIT_FILE"))." >&2
            CAPTURE_FAILED=1
        fi
        if [[ -s "$PCAP_EXIT_FILE" ]]; then
            echo "tcpdump/PCAP exited before simulation completed (status $(<"$PCAP_EXIT_FILE"))." >&2
            CAPTURE_FAILED=1
        fi

        # stop the data collection
        tmux send-keys -t "$SCAP_SESSION" C-c
        tmux send-keys -t "$PCAP_SESSION" C-c

        # Do not read a capture until its writer has actually returned. A fixed
        # sleep could race with a slow Sysdig flush and accept a partial file.
        wait_for_capture_stop "$SCAP_EXIT_FILE" "Sysdig/SCAP" 30
        wait_for_capture_stop "$PCAP_EXIT_FILE" "tcpdump/PCAP" 30

        # Capture readers must never hold the host runner indefinitely. stdin
        # is detached from the terminal and GNU timeout also kills a reader
        # that becomes stopped or otherwise fails to return.
        if ! timeout --kill-after=5s 30s \
            env SYSDIG_PLUGIN_DIR="$SYSDIG_PLUGIN_DIR" \
            "$SYSDIG_BIN" -r "$SCAP_FILE" -n 1 \
            </dev/null >/dev/null 2>&1; then
            echo "Invalid SCAP output: $SCAP_FILE" >&2
            exit 1
        fi
        if ! timeout --kill-after=5s 15s \
            tcpdump -nn -r "$PCAP_FILE" -c 1 \
            </dev/null >/dev/null 2>&1; then
            echo "Invalid PCAP output: $PCAP_FILE" >&2
            exit 1
        fi

        echo "Capture validated: $SCAP_FILE"
        echo "Capture validated: $PCAP_FILE"

        if (( CAPTURE_FAILED != 0 )); then
            echo "Capture stopped unexpectedly during simulation." >&2
            exit 1
        fi
        if (( SIMULATION_RC != 0 )); then
            echo "Simulation failed with exit code $SIMULATION_RC." >&2
            exit "$SIMULATION_RC"
        fi
        rm -f -- "$SCAP_EXIT_FILE" "$PCAP_EXIT_FILE"
        SCAP_EXIT_FILE=""
        PCAP_EXIT_FILE=""
    done
done
