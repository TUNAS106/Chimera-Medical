# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
# system config
import os

from dotenv import load_dotenv

# Load a repository-local .env first so it can define CHIMERA_BASE_DIR. The
# runtime .env under base_dir is loaded next for the original Docker layout.
load_dotenv()
base_dir = os.getenv("CHIMERA_BASE_DIR", "/data/Chimera")  ###### 1 #######
env_path = f"{base_dir}/.env"
load_dotenv(env_path)

# scenario name
scenario_name = os.getenv("CHIMERA_SCENARIO_NAME", "chimera_scenario_1")

# company_id = "tech_company" ###### 2 #######
# company_id = "finance_corporation"
company_id = "medical_institution"

# company_type = "Game Company"
# company_type = "Finance Corporation (Quantitative Hedge Fund)" #
company_type = "Medical Institution (Small Community Hospital)"  ###### 3 #######

# profile output directory
profile_output_dir = f"{base_dir}/{scenario_name}/generated_members"
# attack directory
attack_dir = "/data/attacks"
# attack log directory
attack_schedule_dir = f"{base_dir}/{scenario_name}/attack_schedule"

company_config_path = f"{base_dir}/{scenario_name}/team/{company_id}.json"

# meeting log directory
meeting_log_dir = f"{base_dir}/{scenario_name}/meeting_logs"
# initial schedule directory
init_schedule_dir = f"{base_dir}/{scenario_name}/init_schedule"
# execution log directory
execution_log_dir = f"{base_dir}/{scenario_name}/execution_logs"
# attack log directory
attack_log_dir = f"{base_dir}/{scenario_name}/attack_logs"

# goal of the company
# goal = "The goal of your company is to construct a Third-person shooter game from the beginning." ####### 4 #######
# goal = "The goal of your company is to design and register a market-neutral statistical arbitrage fund targeting UHNWIs (Ultra-High-Net-Worth Individuals) under SEC regulations from the beginning."
goal = "The goal of your institution (small community hospital) is to complete electronic health record collection and seasonal influenza trend analysis from the beginning."

period = int(os.getenv("CHIMERA_PERIOD", "2"))
employee_number = int(os.getenv("CHIMERA_EMPLOYEE_NUMBER", "5"))

# date for starters
base_date = "2025-05-02"

# maximum number of attempts for query LLM for structured output
max_attempt = 5
# maximum query loop
round_limit = 5

# loaf parameters
loaf_rate = 0.3
loaf_interval = 40

# time simulation
sim_seconds = 15
interval_seconds = 5

# This flag controls Chimera's browser/search tools, not whether the model
# weights were loaded offline on Kaggle. Qwen3-VL needs this set to False to
# inspect live web pages and screenshots through BrowserToolkit.
offline_mode = os.getenv("CHIMERA_OFFLINE_MODE", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Daily web access has three explicit modes:
# - llm_only: no public web tools (the model answers from its own knowledge),
# - search_only: lightweight search/fetch over HTTP without Chromium,
# - browser: full Playwright browser automation for deliberately selected runs.
#
# search_only is the safe default for the 16 GiB local host.  It still creates
# realistic DNS/TLS traffic for PCAP while avoiding one Chromium tree per task.
web_mode = os.getenv("CHIMERA_WEB_MODE", "search_only").strip().lower()
if offline_mode:
    web_mode = "llm_only"
if web_mode not in {"llm_only", "search_only", "browser"}:
    raise ValueError(
        "CHIMERA_WEB_MODE must be llm_only, search_only, or browser."
    )

# Activity workers are queued as lightweight task specifications.  Only this
# many OS processes may exist at once; queued activities do not consume a PID.
max_concurrent_tasks = max(
    1, int(os.getenv("CHIMERA_MAX_CONCURRENT_TASKS", "3"))
)
max_aux_model_calls = max(
    1, int(os.getenv("CHIMERA_MAX_AUX_MODEL_CALLS", "1"))
)
vllm_max_num_seqs = max(
    1, int(os.getenv("CHIMERA_VLLM_MAX_NUM_SEQS", "4"))
)
if max_concurrent_tasks + max_aux_model_calls > vllm_max_num_seqs:
    raise ValueError(
        "CHIMERA_MAX_CONCURRENT_TASKS + CHIMERA_MAX_AUX_MODEL_CALLS "
        "must not exceed CHIMERA_VLLM_MAX_NUM_SEQS."
    )
if web_mode == "browser" and max_concurrent_tasks > 2:
    raise ValueError(
        "Browser mode is limited to 2 concurrent activity tasks on this "
        "16 GiB host. Set CHIMERA_MAX_CONCURRENT_TASKS=2."
    )
task_timeout_seconds = max(
    30.0, float(os.getenv("CHIMERA_TASK_TIMEOUT_SECONDS", "900"))
)
task_terminate_grace_seconds = max(
    1.0, float(os.getenv("CHIMERA_TASK_TERMINATE_GRACE_SECONDS", "10"))
)

# A workday is bounded independently of whatever an LLM proposes during an
# email-triggered replan. Reply depth and daily quotas provide a second line of
# defence against acknowledgement emails recursively generating more work.
workday_start = os.getenv("CHIMERA_WORKDAY_START", "08:00:00").strip()
workday_end = os.getenv("CHIMERA_WORKDAY_END", "18:00:00").strip()
max_email_reply_depth = max(
    0, int(os.getenv("CHIMERA_MAX_EMAIL_REPLY_DEPTH", "1"))
)
max_daily_email_replies = max(
    0, int(os.getenv("CHIMERA_MAX_DAILY_EMAIL_REPLIES", "12"))
)
max_daily_replans = max(
    0, int(os.getenv("CHIMERA_MAX_DAILY_REPLANS", "12"))
)

# Lightweight fetch limits bound memory, tool output, redirect loops and
# repeated CAPTCHA/challenge pages.
web_fetch_max_bytes = max(
    65536, int(os.getenv("CHIMERA_WEB_FETCH_MAX_BYTES", "1048576"))
)
web_fetch_max_chars = max(
    1000, int(os.getenv("CHIMERA_WEB_FETCH_MAX_CHARS", "12000"))
)
web_fetch_max_redirects = max(
    0, int(os.getenv("CHIMERA_WEB_FETCH_MAX_REDIRECTS", "3"))
)
web_fetch_require_search_result = os.getenv(
    "CHIMERA_WEB_FETCH_REQUIRE_SEARCH_RESULT", "true"
).lower() in {"1", "true", "yes", "on"}
web_fetch_max_failures = min(
    5, max(1, int(os.getenv("CHIMERA_WEB_FETCH_MAX_FAILURES", "2")))
)
web_query_max_chars = max(
    50, int(os.getenv("CHIMERA_WEB_QUERY_MAX_CHARS", "500"))
)
browser_round_limit = max(
    1, int(os.getenv("CHIMERA_BROWSER_ROUND_LIMIT", "6"))
)
max_tool_argument_chars = max(
    512, int(os.getenv("CHIMERA_MAX_TOOL_ARGUMENT_CHARS", "4096"))
)
activity_max_tool_iterations = min(
    12,
    max(3, int(os.getenv("CHIMERA_ACTIVITY_MAX_TOOL_ITERATIONS", "8"))),
)
activity_semantic_retries = min(
    2, max(0, int(os.getenv("CHIMERA_ACTIVITY_SEMANTIC_RETRIES", "1")))
)

# Weekly planning is an internal coordination task and should not need web
# search. Keeping this disabled prevents irrelevant search-tool loops and
# third-party rate limits from blocking company preparation.
meeting_enable_search = os.getenv(
    "CHIMERA_MEETING_ENABLE_SEARCH", "false"
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Public web search uses keyless Bing HTML. Force short, bounded timeouts so a
# broken route cannot stall an employee process indefinitely.
web_search_connect_timeout = float(
    os.getenv("CHIMERA_WEB_SEARCH_CONNECT_TIMEOUT", "5")
)
web_search_timeout = float(os.getenv("CHIMERA_WEB_SEARCH_TIMEOUT", "15"))
web_search_max_attempts = min(
    6, max(1, int(os.getenv("CHIMERA_WEB_SEARCH_MAX_ATTEMPTS", "4")))
)

### Foundation Model
### Self-hosted Qwen3-VL through a vLLM OpenAI-compatible endpoint
foundation_corp = os.getenv("CHIMERA_FOUNDATION_CORP", "vllm")
foundation_model = os.getenv(
    "CHIMERA_FOUNDATION_MODEL", "Qwen/Qwen3-VL-30B-A3B-Instruct"
)
_self_hosted_backend = foundation_corp.lower().replace("-", "_") in {
    "vllm",
    "openai_compatible",
}
foundation_base_url = os.getenv(
    "CHIMERA_FOUNDATION_BASE_URL",
    os.getenv(
        "VLLM_BASE_URL",
        "http://127.0.0.1:8000/v1" if _self_hosted_backend else "",
    ),
)
foundation_api_key = os.getenv(
    "CHIMERA_FOUNDATION_API_KEY",
    (
        "chimera-local-change-me"
        if _self_hosted_backend
        else os.getenv("OPENAI_API_KEY", "")
    ),
)
foundation_timeout = float(os.getenv("CHIMERA_FOUNDATION_TIMEOUT", "600"))
foundation_max_retries = max(
    0, int(os.getenv("CHIMERA_FOUNDATION_MAX_RETRIES", "0"))
)
foundation_transient_retries = min(
    4,
    max(0, int(os.getenv("CHIMERA_FOUNDATION_TRANSIENT_RETRIES", "2"))),
)
foundation_retry_base_seconds = min(
    10.0,
    max(
        0.1,
        float(os.getenv("CHIMERA_FOUNDATION_RETRY_BASE_SECONDS", "1")),
    ),
)
foundation_max_tokens = int(os.getenv("CHIMERA_FOUNDATION_MAX_TOKENS", "8192"))
foundation_top_p = float(os.getenv("CHIMERA_FOUNDATION_TOP_P", "0.9"))

# Direct run_llm() calls are recorded separately from Camel/OWL task traces.
model_log_dir = os.path.join(base_dir, scenario_name, "model_logs")
log_model_content = os.getenv("CHIMERA_LOG_MODEL_CONTENT", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Legacy provider key used by the Google/DeepSeek/xAI branches.
api_key = os.getenv(
    "CHIMERA_API_KEY",
    os.getenv(
        "GEMINI_API_KEY",
        os.getenv(
            "DEEPSEEK_API_KEY",
            os.getenv("XAI_API_KEY", foundation_api_key),
        ),
    ),
)

### google
# foundation_corp = "google"
# foundation_model = "gemini-2.0-flash"
# api_key = 'XXX'

# ### deepseek
# foundation_corp = "deepseek"
# foundation_model = "deepseek-chat"
# api_key = "XXX"

# ### grok
# foundation_corp = "xai"
# foundation_model = "grok-3-mini"
# api_key = "XXX"
