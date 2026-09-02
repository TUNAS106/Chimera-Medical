# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# SPDX-License-Identifier: MIT
"""Remove signed endpoint paths from existing JSONL audit records."""

from __future__ import annotations

import argparse
import json
import os
import tempfile

import config
from model_backend import safe_endpoint_label


def sanitize_jsonl(path: str) -> tuple[int, int]:
    """Rewrite endpoint fields atomically, preserving every audit record."""

    if not os.path.isfile(path):
        return 0, 0
    record_count = 0
    changed_count = 0
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".model-audit-sanitized-", suffix=".jsonl", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output_file:
            with open(path, "r", encoding="utf-8") as input_file:
                for line in input_file:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        output_file.write(line)
                        continue
                    record_count += 1
                    endpoint = record.get("endpoint")
                    if isinstance(endpoint, str):
                        safe_endpoint = safe_endpoint_label(endpoint)
                        if safe_endpoint != endpoint:
                            record["endpoint"] = safe_endpoint
                            changed_count += 1
                    output_file.write(
                        json.dumps(record, ensure_ascii=False, default=str)
                        + "\n"
                    )
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise
    return record_count, changed_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default=os.path.join(config.model_log_dir, "model_calls.jsonl"),
    )
    args = parser.parse_args()
    records, changed = sanitize_jsonl(args.path)
    print(
        f"Model audit sanitized: records={records} changed_endpoints={changed}"
    )


if __name__ == "__main__":
    main()
