#!/usr/bin/env bash
# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/prepare_company.sh"

echo "======= Running complete daily simulation with capture ======="
bash "$SCRIPT_DIR/daily_execution.sh"
