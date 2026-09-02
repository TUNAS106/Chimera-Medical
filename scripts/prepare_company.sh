#!/usr/bin/env bash
# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

CONTAINER_NAME="${CHIMERA_CONTAINER_NAME:-chimera2}"
STATUS_ONLY=false

if [[ "${1:-}" == "--status-only" ]]; then
    STATUS_ONLY=true
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--status-only]" >&2
    exit 2
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]]; then
    echo "Container $CONTAINER_NAME is not running." >&2
    exit 1
fi

echo "Running resumable company preparation in $CONTAINER_NAME..."
if [[ "$STATUS_ONLY" == "true" ]]; then
    docker exec "$CONTAINER_NAME" bash \
        /data/Chimera/scripts/prepare_company_in_container.sh --status-only
else
    docker exec "$CONTAINER_NAME" bash \
        /data/Chimera/scripts/prepare_company_in_container.sh
fi
