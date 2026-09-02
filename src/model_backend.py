# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
"""Shared CAMEL model construction and safe run metadata logging."""

import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from camel.models import ModelFactory
from camel.types import ModelPlatformType

import config

logger = logging.getLogger(__name__)


def safe_endpoint_label(url: str | None = None) -> str:
    """Return an audit-safe endpoint label without signed URL path tokens."""

    endpoint = url if url is not None else config.foundation_base_url
    if not endpoint:
        return "provider-default"
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return "configured-endpoint"
    if not parsed.scheme or not parsed.netloc:
        return "configured-endpoint"
    version_suffix = "/v1" if parsed.path.rstrip("/").endswith("/v1") else ""
    return f"{parsed.scheme}://{parsed.netloc}/...{version_suffix}"


def _provider_name() -> str:
    return config.foundation_corp.lower().replace("-", "_")


def _model_config(temperature: float) -> dict:
    return {
        "temperature": temperature,
        "top_p": config.foundation_top_p,
        "max_tokens": config.foundation_max_tokens,
        "stream": False,
    }


def create_camel_model(temperature: float = 0):
    """Create a CAMEL backend that uses the configured foundation model.

    Qwen3-VL is exposed by the Kaggle vLLM server under an OpenAI-compatible
    model name. Passing the name as a string is intentional: the patched CAMEL
    version accepts open-source model identifiers that are not present in its
    ModelType enum.
    """

    provider = _provider_name()
    platform_map = {
        "openai": ModelPlatformType.OPENAI,
        "google": ModelPlatformType.GEMINI,
        "deepseek": ModelPlatformType.DEEPSEEK,
        "vllm": ModelPlatformType.VLLM,
        "openai_compatible": ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        "xai": ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
    }
    if provider not in platform_map:
        raise ValueError(
            "Invalid foundation_corp. Choose 'vllm', 'openai_compatible', "
            "'openai', 'google', 'deepseek', or 'xai'."
        )

    kwargs = {
        "model_platform": platform_map[provider],
        "model_type": config.foundation_model,
        "model_config_dict": _model_config(temperature),
        "timeout": config.foundation_timeout,
    }

    if provider in {"vllm", "openai_compatible"}:
        if not config.foundation_base_url:
            raise ValueError(
                "CHIMERA_FOUNDATION_BASE_URL is required for the self-hosted model."
            )
        kwargs["api_key"] = config.foundation_api_key or "EMPTY"
        kwargs["url"] = config.foundation_base_url
    elif provider == "xai":
        kwargs["api_key"] = config.api_key
        kwargs["url"] = config.foundation_base_url or "https://api.x.ai/v1"
    elif provider == "openai" and config.foundation_base_url:
        kwargs["api_key"] = config.foundation_api_key
        kwargs["url"] = config.foundation_base_url
    elif config.api_key and config.api_key != "XXX":
        kwargs["api_key"] = config.api_key

    logger.info(
        "Creating CAMEL model provider=%s model=%s endpoint=%s temperature=%s",
        provider,
        config.foundation_model,
        safe_endpoint_label(),
        temperature,
    )
    return ModelFactory.create(**kwargs)


def model_runtime_description() -> str:
    """Return a safe description for daemon/task logs (never includes secrets)."""

    return (
        f"provider={_provider_name()} model={config.foundation_model} "
        f"endpoint={safe_endpoint_label()} "
        f"timeout={config.foundation_timeout}s max_tokens={config.foundation_max_tokens}"
    )


def write_run_metadata(log_dir: str, workflow: str, **context) -> str:
    """Append model/runtime metadata for one workflow without exposing API keys."""

    os.makedirs(log_dir, exist_ok=True)
    metadata_path = os.path.join(log_dir, "run_metadata.jsonl")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workflow": workflow,
        "provider": _provider_name(),
        "model": config.foundation_model,
        "endpoint": safe_endpoint_label(),
        "timeout_seconds": config.foundation_timeout,
        "max_tokens": config.foundation_max_tokens,
        "top_p": config.foundation_top_p,
        "web_mode": config.web_mode,
        "pid": os.getpid(),
        **context,
    }
    payload = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with open(metadata_path, "a", encoding="utf-8") as metadata_file:
        fcntl.flock(metadata_file.fileno(), fcntl.LOCK_EX)
        try:
            metadata_file.write(payload)
            metadata_file.flush()
        finally:
            fcntl.flock(metadata_file.fileno(), fcntl.LOCK_UN)
    return metadata_path
