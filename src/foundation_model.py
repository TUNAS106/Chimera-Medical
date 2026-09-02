# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Foundation-model access and structured audit logging."""

import fcntl
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

import config
from model_backend import safe_endpoint_label

load_dotenv(config.env_path)
logger = logging.getLogger(__name__)


class TransientFoundationModelError(RuntimeError):
    """Raised after bounded retries exhaust a temporary model failure."""


def _is_transient_model_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in {408, 409, 429} or exc.status_code >= 500
    return False


def _create_chat_completion_with_retry(client, request_kwargs, audit):
    """Retry only explicit transport/temporary HTTP failures with backoff."""

    for attempt in range(config.foundation_transient_retries + 1):
        try:
            return client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            if not _is_transient_model_error(exc):
                raise
            if attempt >= config.foundation_transient_retries:
                raise TransientFoundationModelError(
                    "Foundation model remained unavailable after "
                    f"{attempt + 1} attempt(s): {exc}"
                ) from exc

            delay = config.foundation_retry_base_seconds * (2**attempt)
            audit.setdefault("transient_retries", []).append(
                {
                    "attempt": attempt + 1,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "delay_seconds": delay,
                }
            )
            logger.warning(
                "Transient foundation-model failure on attempt %s/%s; "
                "retrying in %.1fs: %s",
                attempt + 1,
                config.foundation_transient_retries + 1,
                delay,
                exc,
            )
            time.sleep(delay)


def _provider_name() -> str:
    return config.foundation_corp.lower().replace("-", "_")


def _openai_client(require_base_url: bool = False) -> OpenAI:
    if require_base_url and not config.foundation_base_url:
        raise ValueError(
            "CHIMERA_FOUNDATION_BASE_URL is required for the self-hosted model."
        )
    kwargs = {
        "api_key": config.foundation_api_key or os.getenv("OPENAI_API_KEY") or "EMPTY",
        "timeout": config.foundation_timeout,
        "max_retries": config.foundation_max_retries,
    }
    if config.foundation_base_url:
        kwargs["base_url"] = config.foundation_base_url
    return OpenAI(**kwargs)


def _usage_dict(response) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump(exclude_none=True)
    return {
        key: getattr(usage, key)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if getattr(usage, key, None) is not None
    }


def _append_model_audit(record: dict) -> None:
    """Append one JSONL record safely across Chimera threads/processes."""

    os.makedirs(config.model_log_dir, exist_ok=True)
    log_path = os.path.join(config.model_log_dir, "model_calls.jsonl")
    payload = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with open(log_path, "a", encoding="utf-8") as log_file:
        fcntl.flock(log_file.fileno(), fcntl.LOCK_EX)
        try:
            log_file.write(payload)
            log_file.flush()
        finally:
            fcntl.flock(log_file.fileno(), fcntl.LOCK_UN)


def _safe_append_model_audit(record: dict) -> None:
    """Keep model execution alive if only the auxiliary audit path fails."""

    try:
        _append_model_audit(record)
    except OSError:
        logger.exception("Unable to append the direct model audit record")


def _audit_record(
    request_id: str,
    operation: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> dict:
    record = {
        "request_id": request_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": _provider_name(),
        "model": config.foundation_model,
        "endpoint": safe_endpoint_label(),
        "operation": operation,
        "temperature": temperature,
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "system_prompt_chars": len(system_prompt),
        "user_prompt_chars": len(user_prompt),
    }
    if config.log_model_content:
        record["system_prompt"] = system_prompt
        record["user_prompt"] = user_prompt
    return record


def run_llm(
    system_prompt,
    user_prompt,
    temperature=0,
    operation="unspecified",
):
    """Run one completion through the configured provider and audit the call."""

    provider = _provider_name()
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    audit = _audit_record(
        request_id, operation, system_prompt, user_prompt, temperature
    )

    try:
        if provider in {"openai", "vllm", "openai_compatible"}:
            client = _openai_client(
                require_base_url=provider in {"vllm", "openai_compatible"}
            )
            response = _create_chat_completion_with_retry(
                client,
                {
                    "model": config.foundation_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "top_p": config.foundation_top_p,
                    "max_tokens": config.foundation_max_tokens,
                    "stream": False,
                },
                audit,
            )
            llm_output = response.choices[0].message.content
            usage = _usage_dict(response)

        elif provider == "google":
            # Keep google-genai optional for Qwen/vLLM-only deployments.
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=config.api_key)
            response = client.models.generate_content(
                model=config.foundation_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    top_p=config.foundation_top_p,
                    max_output_tokens=config.foundation_max_tokens,
                ),
            )
            llm_output = response.text
            usage = {}

        elif provider == "deepseek":
            client = OpenAI(
                api_key=config.api_key,
                base_url="https://api.deepseek.com",
                timeout=config.foundation_timeout,
                max_retries=3,
            )
            response = client.chat.completions.create(
                model=config.foundation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                top_p=config.foundation_top_p,
                max_tokens=config.foundation_max_tokens,
                stream=False,
            )
            llm_output = response.choices[0].message.content
            usage = _usage_dict(response)

        elif provider == "xai":
            client = OpenAI(
                api_key=config.api_key,
                base_url=config.foundation_base_url or "https://api.x.ai/v1",
                timeout=config.foundation_timeout,
                max_retries=3,
            )
            response = client.chat.completions.create(
                model=config.foundation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                top_p=config.foundation_top_p,
                max_tokens=config.foundation_max_tokens,
                stream=False,
            )
            llm_output = response.choices[0].message.content
            usage = _usage_dict(response)

        else:
            raise ValueError(
                "Invalid foundation_corp. Choose 'vllm', 'openai_compatible', "
                "'openai', 'google', 'deepseek', or 'xai'."
            )

        if llm_output is None:
            raise RuntimeError("The model returned an empty message content.")

        audit.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "status": "success",
                "usage": usage,
                "response_chars": len(llm_output),
                "retry_count": len(audit.get("transient_retries", [])),
            }
        )
        if config.log_model_content:
            audit["response"] = llm_output
        _safe_append_model_audit(audit)
        return llm_output

    except Exception as exc:
        audit.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _safe_append_model_audit(audit)
        raise
