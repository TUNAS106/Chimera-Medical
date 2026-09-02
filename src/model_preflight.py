# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Fail fast when the configured OpenAI-compatible model is unavailable."""

from openai import OpenAI

import config
from model_backend import safe_endpoint_label


def main() -> None:
    client = OpenAI(
        base_url=config.foundation_base_url,
        api_key=config.foundation_api_key or "EMPTY",
        timeout=min(config.foundation_timeout, 60),
        max_retries=0,
    )
    try:
        models = client.models.list()
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        status = f" HTTP {status_code}" if status_code is not None else ""
        raise RuntimeError(
            f"Model endpoint {safe_endpoint_label()} failed{status} "
            f"({type(exc).__name__})."
        ) from None
    model_ids = [model.id for model in models.data]
    if config.foundation_model not in model_ids:
        raise RuntimeError(
            f"Configured model {config.foundation_model!r} is unavailable; "
            f"server exposed {len(model_ids)} model(s)."
        )

    # /models alone can succeed while the inference engine is unhealthy.  A
    # tiny deterministic request verifies the exact chat-completions path used
    # by all workers without writing the signed endpoint to stdout.
    try:
        response = client.chat.completions.create(
            model=config.foundation_model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: CHIMERA_READY",
                }
            ],
            temperature=0,
            max_tokens=32,
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        status = f" HTTP {status_code}" if status_code is not None else ""
        raise RuntimeError(
            f"Chat completion preflight failed{status} ({type(exc).__name__})."
        ) from None
    content = (response.choices[0].message.content or "").strip()
    if "CHIMERA_READY" not in content:
        raise RuntimeError("The model responded, but the readiness marker was missing.")

    print(
        "Model preflight passed: "
        f"model={config.foundation_model} endpoint={safe_endpoint_label()}"
    )


if __name__ == "__main__":
    main()
