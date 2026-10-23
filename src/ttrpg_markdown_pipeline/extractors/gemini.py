import argparse
import contextlib
import json
import os
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf
from google import genai
from google.genai import errors, types

from ttrpg_markdown_pipeline.common import GEMINI_TAG, clean_path, load_env_file, resolve_md_output
from ttrpg_markdown_pipeline.rules.cosmere import DEFAULT_PROMPT

MIN_SUPPORTED_MAJOR_VERSION = 3

# Default static fallback if API dynamic discovery is unavailable
DEFAULT_DESIRABILITY_PATH = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
]
DESIRABILITY_PATH = DEFAULT_DESIRABILITY_PATH

_MODEL_POOL_CACHE: dict[str, list[str]] = {}
_EXHAUSTED_MODELS: set[str] = set()
QUOTA_STATE_FILE = Path(".gemini_quota_state.json")

CHUNK_BOUNDARY_SENTINEL = "\n\n<!-- OKF_CHUNK_BOUNDARY -->\n\n"

DEFAULT_GENERATION_CONFIG = types.GenerateContentConfig(
    temperature=0.1,
    max_output_tokens=65536,
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_budget=2048),
)


def is_valid_json_chunk(text: str) -> bool:
    """Validates that text contains a well-formed JSON list of dictionary objects."""
    if not text or not text.strip():
        return False
    candidate = text.strip()
    # Strip optional markdown code fences
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()
    try:
        data = json.loads(candidate)
        return isinstance(data, list) and all(isinstance(item, dict) for item in data)
    except Exception:
        return False


def _safe_int(val: Any) -> int:
    """Safely converts an integer metric (ignoring MagicMocks or booleans)."""
    return val if isinstance(val, int) and not isinstance(val, bool) else 0


def extract_response_usage(response: Any) -> dict[str, Any]:
    """Extracts token counts and finish reason from a Gemini GenerateContentResponse."""
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = _safe_int(getattr(usage, "prompt_token_count", 0)) if usage else 0
    candidates_tokens = _safe_int(getattr(usage, "candidates_token_count", 0)) if usage else 0
    thoughts_tokens = _safe_int(getattr(usage, "thoughts_token_count", 0)) if usage else 0
    total_tokens = _safe_int(getattr(usage, "total_token_count", 0)) if usage else 0
    if total_tokens == 0 and (prompt_tokens or candidates_tokens or thoughts_tokens):
        total_tokens = prompt_tokens + candidates_tokens + thoughts_tokens

    finish_reason = "STOP"
    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, (list, tuple)) and candidates:
        raw_reason = getattr(candidates[0], "finish_reason", None)
        if raw_reason is not None:
            name = getattr(raw_reason, "name", None)
            if isinstance(name, str) and name:
                finish_reason = name
            elif isinstance(raw_reason, str) and raw_reason:
                finish_reason = raw_reason

    return {
        "prompt_tokens": prompt_tokens,
        "candidates_tokens": candidates_tokens,
        "thoughts_tokens": thoughts_tokens,
        "total_tokens": total_tokens,
        "finish_reason": finish_reason,
    }


@dataclass
class ModelUsageStats:
    """Aggregated token usage, call counts, latency, and finish reasons for a single model."""

    calls_attempted: int = 0
    calls_succeeded: int = 0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    total_latency_s: float = 0.0
    finish_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class ErrorRecord:
    """Detailed diagnostic record for a model API error or empty response."""

    timestamp: str
    context: str
    model: str
    error_type: str
    status_code: int | None
    quota_id: str | None
    quota_limit: str | None
    retry_delay: str | None
    message: str
    resolution: str


@dataclass
class ModelSwitchRecord:
    """Records a fallback switch from one model in the desirability pool to the next."""

    timestamp: str
    context: str
    from_model: str
    to_model: str
    error_type: str
    reason: str
    marked_exhausted: bool


@dataclass
class RunReport:
    """Aggregates model usage indicators, model switches, and error diagnostics across a pipeline run."""

    model_usage: dict[str, ModelUsageStats] = field(default_factory=dict)
    switches: list[ModelSwitchRecord] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)
    cached_chunks_skipped: int = 0

    def reset(self) -> None:
        self.model_usage.clear()
        self.switches.clear()
        self.errors.clear()
        self.cached_chunks_skipped = 0

    def record_attempt(self, model: str) -> None:
        stats = self.model_usage.setdefault(model, ModelUsageStats())
        stats.calls_attempted += 1

    def record_success(self, model: str, response: Any, latency_s: float = 0.0) -> dict[str, Any]:
        stats = self.model_usage.setdefault(model, ModelUsageStats())
        stats.calls_succeeded += 1
        stats.total_latency_s += max(0.0, latency_s)
        usage = extract_response_usage(response)
        stats.prompt_tokens += usage["prompt_tokens"]
        stats.candidates_tokens += usage["candidates_tokens"]
        stats.thoughts_tokens += usage["thoughts_tokens"]
        stats.total_tokens += usage["total_tokens"]
        reason = usage["finish_reason"]
        stats.finish_reasons[reason] = stats.finish_reasons.get(reason, 0) + 1
        return usage

    def record_error(
        self,
        *,
        timestamp: str,
        context: str,
        model: str,
        error_type: str,
        status_code: int | None,
        quota_id: str | None,
        quota_limit: str | None,
        retry_delay: str | None,
        message: str,
        resolution: str,
    ) -> None:
        self.errors.append(
            ErrorRecord(
                timestamp=timestamp,
                context=context,
                model=model,
                error_type=error_type,
                status_code=status_code,
                quota_id=quota_id,
                quota_limit=quota_limit,
                retry_delay=retry_delay,
                message=message,
                resolution=resolution,
            )
        )

    def record_switch(
        self,
        *,
        timestamp: str,
        context: str,
        from_model: str,
        to_model: str,
        error_type: str,
        reason: str,
        marked_exhausted: bool,
    ) -> None:
        self.switches.append(
            ModelSwitchRecord(
                timestamp=timestamp,
                context=context,
                from_model=from_model,
                to_model=to_model,
                error_type=error_type,
                reason=reason,
                marked_exhausted=marked_exhausted,
            )
        )

    def format_report(self) -> str:
        """Formats a detailed Markdown/CLI run report of model usage, switches, and error diagnostics."""
        lines: list[str] = [
            "# Gemini Extraction Run Report",
            "",
        ]
        total_attempts = sum(s.calls_attempted for s in self.model_usage.values())
        total_succeeded = sum(s.calls_succeeded for s in self.model_usage.values())
        total_prompt = sum(s.prompt_tokens for s in self.model_usage.values())
        total_output = sum(s.candidates_tokens for s in self.model_usage.values())
        total_thoughts = sum(s.thoughts_tokens for s in self.model_usage.values())
        total_tokens = sum(s.total_tokens for s in self.model_usage.values())

        lines.extend(
            [
                "## 1. Overall Summary",
                f"- **API Calls (Succeeded / Attempted):** {total_succeeded} / {total_attempts}",
                f"- **Cached Chunks Reused:** {self.cached_chunks_skipped}",
                f"- **Total Tokens Used:** {total_tokens:,} "
                f"(Prompt: {total_prompt:,} | Output: {total_output:,} | Thinking: {total_thoughts:,})",
                f"- **Model Switches Triggered:** {len(self.switches)}",
                f"- **Total Error Events:** {len(self.errors)}",
                f"- **Models Marked Exhausted/Unavailable:** "
                f"{', '.join(sorted(_EXHAUSTED_MODELS)) if _EXHAUSTED_MODELS else 'None'}",
                "",
                "## 2. Per-Model Usage & Token Indicators",
            ]
        )

        if not self.model_usage:
            lines.append("_No live model calls were made during this run (all chunks served from cache)._")
        else:
            lines.extend(
                [
                    "| Model | Succeeded / Attempted | Prompt Tokens | Output Tokens | Thinking Tokens | Total Tokens | Avg Latency | Finish Reasons |",  # noqa: E501
                    "| :--- | :---: | ---: | ---: | ---: | ---: | ---: | :--- |",
                ]
            )
            for model_name, st in self.model_usage.items():
                avg_lat = f"{st.total_latency_s / st.calls_succeeded:.1f}s" if st.calls_succeeded else "-"
                reasons_str = (
                    ", ".join(f"{k}:{v}" for k, v in sorted(st.finish_reasons.items())) if st.finish_reasons else "-"
                )
                lines.append(
                    f"| `{model_name}` | {st.calls_succeeded} / {st.calls_attempted} | "
                    f"{st.prompt_tokens:,} | {st.candidates_tokens:,} | {st.thoughts_tokens:,} | "
                    f"{st.total_tokens:,} | {avg_lat} | {reasons_str} |"
                )

        lines.extend(["", "## 3. Model Switches (`from -> to` & Why)"])
        if not self.switches:
            lines.append("_No model switches occurred._")
        else:
            for idx, sw in enumerate(self.switches, 1):
                ctx_prefix = f"[{sw.context}] " if sw.context else ""
                perm_tag = " *(marked session-exhausted)*" if sw.marked_exhausted else " *(chunk-only fallback)*"
                lines.append(
                    f"{idx}. `{sw.timestamp}` {ctx_prefix}**`{sw.from_model}` -> `{sw.to_model}`** "
                    f"[`{sw.error_type}`]: {sw.reason}{perm_tag}"
                )

        lines.extend(["", "## 4. Error Breakdown & Diagnostics"])
        if not self.errors:
            lines.append("_Zero API errors encountered._")
        else:
            counts_by_type: dict[str, int] = {}
            for err in self.errors:
                counts_by_type[err.error_type] = counts_by_type.get(err.error_type, 0) + 1
            summary_parts = [f"`{k}`: {v}" for k, v in sorted(counts_by_type.items())]
            lines.append(f"**Counts by Error Type:** {', '.join(summary_parts)}")
            lines.append("")
            for idx, err in enumerate(self.errors, 1):
                ctx_prefix = f"[{err.context}] " if err.context else ""
                meta_bits: list[str] = []
                if err.status_code is not None:
                    meta_bits.append(f"HTTP {err.status_code}")
                if err.quota_id:
                    meta_bits.append(f"quotaId={err.quota_id}")
                if err.quota_limit is not None:
                    meta_bits.append(f"limit={err.quota_limit}")
                if err.retry_delay:
                    meta_bits.append(f"retry_in={err.retry_delay}")
                meta_str = f" ({', '.join(meta_bits)})" if meta_bits else ""
                lines.append(
                    f"{idx}. `{err.timestamp}` {ctx_prefix}`{err.model}` — **`{err.error_type}`**{meta_str}: "
                    f"{err.message} -> *{err.resolution}*"
                )

        lines.append("")
        return "\n".join(lines)


_GLOBAL_RUN_REPORT = RunReport()


def get_run_report() -> RunReport:
    """Returns the active session RunReport singleton."""
    return _GLOBAL_RUN_REPORT


def reset_run_report() -> RunReport:
    """Clears and returns the active session RunReport singleton."""
    _GLOBAL_RUN_REPORT.reset()
    return _GLOBAL_RUN_REPORT


def discover_model_pool(client: genai.Client | None = None, strategy: str = "quality") -> list[str]:
    """Dynamically queries Gemini API for available models, filtered and sorted by strategy.

    Strategies:
      - 'pro': Prioritizes Pro models (newest first), then standard Flash, then Flash-Lite.
      - 'quality': Prioritizes standard Flash models by version (newest first), then Pro, then Flash-Lite.
      - 'quota': Prioritizes Flash-Lite models by version (newest first), then standard Flash, then Pro.

    Results are cached in-memory per strategy so discovery runs at most once per session.
    """
    if strategy in _MODEL_POOL_CACHE:
        return _MODEL_POOL_CACHE[strategy]

    if client is None:
        try:
            load_env_file()
            client = genai.Client()
        except Exception:
            return DEFAULT_DESIRABILITY_PATH

    try:
        pattern = re.compile(r"^gemini-(\d+(?:\.\d+)?)-(pro|flash(?:-lite)?)(?:-(preview))?$")
        matches: list[tuple[str, str, tuple[int, ...], int]] = []
        denylist = {x.strip() for x in os.getenv("GEMINI_MODEL_DENYLIST", "").split(",") if x.strip()}

        for m in client.models.list():
            if not m.name:
                continue
            clean = m.name.removeprefix("models/")
            if clean in denylist:
                continue
            res = pattern.match(clean)
            if res and "generateContent" in getattr(m, "supported_actions", []):
                ver_str, flavor, preview_tag = res.groups()
                parts = tuple(int(p) for p in ver_str.split("."))
                if len(parts) == 1:
                    parts = (parts[0], 0)
                if parts[0] < MIN_SUPPORTED_MAJOR_VERSION:
                    continue
                is_stable = 0 if preview_tag else 1
                matches.append((clean, flavor, parts, is_stable))

        if not matches:
            return DEFAULT_DESIRABILITY_PATH

        if strategy == "pro":
            tier_map = {"pro": 3, "flash": 2, "flash-lite": 1}
        elif strategy == "quota":
            tier_map = {"flash-lite": 3, "flash": 2, "pro": 1}
        else:
            tier_map = {"flash": 3, "pro": 2, "flash-lite": 1}

        sorted_models = [
            m[0]
            for m in sorted(
                matches,
                key=lambda x: (tier_map.get(x[1], 0), x[2], x[3]),
                reverse=True,
            )
        ]

        _MODEL_POOL_CACHE[strategy] = sorted_models
        return sorted_models
    except Exception as e:
        print(f"[!] Warning: Could not dynamically list Gemini models ({e}). Using static fallback.")
        return DEFAULT_DESIRABILITY_PATH


def is_daily_quota_exhausted(exc: BaseException) -> bool:
    """Returns True if the error indicates a multi-hour/daily quota lockout or 0-limit quota."""
    err = str(exc).lower()
    if re.search(r"please retry in\s+[0-9ms.]*\d+(?:\.\d+)?\s*[hd]", err):
        return True
    if re.search(r"per[_ ]?day|daily\s+quota", err):
        return True
    return bool(re.search(r"\blimit:\s*0\b", err))


def parse_api_error_diagnostics(exc: BaseException) -> dict[str, Any]:
    """Parses structured quota, retry-delay, and error-type diagnostics from a Gemini API exception."""
    raw_str = str(exc)
    err_lower = raw_str.lower()
    raw_code = getattr(exc, "code", None)
    status_code = raw_code if isinstance(raw_code, int) else None

    quota_id: str | None = None
    m_qid = re.search(r"'quotaId':\s*'([^']+)'", raw_str)
    if m_qid:
        quota_id = m_qid.group(1)
    else:
        m_metric = re.search(r"Quota exceeded for metric:\s*([^\s,\\'\"]+)", raw_str, re.IGNORECASE)
        if m_metric:
            quota_id = m_metric.group(1)

    quota_limit: str | None = None
    m_limit = re.search(r"limit:\s*(\d+)", raw_str, re.IGNORECASE) or re.search(r"'quotaValue':\s*'(\d+)'", raw_str)
    if m_limit:
        quota_limit = m_limit.group(1)

    retry_delay: str | None = None
    retry_seconds: float | None = None
    m_retry = re.search(r"please retry in\s+([0-9dhms.]+)", raw_str, re.IGNORECASE)
    if m_retry:
        raw_delay = m_retry.group(1).rstrip(".")
        # Trim excessive fractional seconds (e.g. 3h37m15.812117684s -> 3h37m15.8s)
        retry_delay = re.sub(r"(\d+\.\d)\d+s", r"\1s", raw_delay)
        total_s = 0.0
        for val, unit in re.findall(r"(\d+(?:\.\d+)?)([dhms])", raw_delay.lower()):
            mult = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}[unit]
            total_s += float(val) * mult
        if total_s > 0:
            retry_seconds = total_s

    if status_code == 429 or "resource_exhausted" in err_lower or "please retry in" in err_lower:
        if quota_limit == "0" or re.search(r"\blimit:\s*0\b", err_lower):
            error_type = "zero_quota_limit"
        elif is_daily_quota_exhausted(exc):
            error_type = "daily_quota_exhausted"
        else:
            error_type = "rate_limit_429"
    elif status_code == 503 or "high demand" in err_lower or "overloaded" in err_lower:
        error_type = "high_demand_503"
    elif status_code == 404 or "no longer available" in err_lower or "not found" in err_lower:
        error_type = "not_found_or_deprecated_404"
    else:
        error_type = f"api_error_{status_code}" if status_code else "api_error"

    raw_msg = getattr(exc, "message", None)
    base_msg = str(raw_msg).strip() if isinstance(raw_msg, str) and raw_msg.strip() else raw_str
    first_line = base_msg.splitlines()[0].strip()
    if len(first_line) > 100:
        first_line = first_line[:97] + "..."

    meta_parts: list[str] = []
    if quota_id:
        meta_parts.append(f"quotaId={quota_id}")
    if quota_limit is not None:
        meta_parts.append(f"limit={quota_limit}")
    if retry_delay:
        meta_parts.append(f"retry_in={retry_delay}")
    meta_suffix = f" [{' | '.join(meta_parts)}]" if meta_parts else ""
    short_message = f"{first_line}{meta_suffix}"

    return {
        "status_code": status_code,
        "error_type": error_type,
        "quota_id": quota_id,
        "quota_limit": quota_limit,
        "retry_delay": retry_delay,
        "retry_seconds": retry_seconds,
        "short_message": short_message,
    }


def load_persisted_quota_state(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Loads active exhausted model state from disk into _EXHAUSTED_MODELS."""
    state_file = path or QUOTA_STATE_FILE
    if not state_file.exists():
        return {}
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        now = time.time()
        valid_state: dict[str, dict[str, Any]] = {}
        for model, info in raw.items():
            if isinstance(info, dict) and info.get("expires_at", 0) > now:
                valid_state[model] = info
                _EXHAUSTED_MODELS.add(model)
        return valid_state
    except Exception:
        return {}


def record_model_exhaustion(
    model: str,
    error_type: str,
    retry_seconds: float | None = None,
    reason: str = "",
    path: Path | None = None,
) -> bool:
    """Marks model exhausted, calculates expiration TTL, and persists state.

    Returns True if model was newly added, False if already exhausted.
    """
    newly_added = model not in _EXHAUSTED_MODELS
    _EXHAUSTED_MODELS.add(model)

    if "PYTEST_CURRENT_TEST" in os.environ and path is None:
        return newly_added

    state_file = path or QUOTA_STATE_FILE
    try:
        state: dict[str, Any] = {}
        if state_file.exists():
            with contextlib.suppress(Exception):
                state = json.loads(state_file.read_text(encoding="utf-8"))
        ttl = (
            86400.0 * 7
            if error_type in ("not_found_or_deprecated_404", "zero_quota_limit")
            else (retry_seconds or 3600.0)
        )
        state[model] = {
            "reason": reason,
            "error_type": error_type,
            "recorded_at": time.time(),
            "expires_at": time.time() + ttl,
        }
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass
    return newly_added


def handle_generation_api_error(
    exc: errors.APIError,
    model: str,
    model_pool: list[str],
    idx: int,
    attempt: int,
    *,
    context: str = "",
    report: RunReport | None = None,
) -> tuple[str, float]:
    """Classifies an APIError, updates quota/report state, and returns (action, backoff_seconds).

    action is either 'cascade' (move to next model in pool) or 'retry' (retry current model).
    """
    active_report = report or _GLOBAL_RUN_REPORT
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diag = parse_api_error_diagnostics(exc)
    err_type = diag["error_type"]
    short_msg = diag["short_message"]

    if is_daily_quota_exhausted(exc):
        newly_exhausted = record_model_exhaustion(
            model, err_type, retry_seconds=diag.get("retry_seconds"), reason=short_msg
        )
        next_model = _next_available_model(model_pool, idx)
        print(f"[{ts}] [!] Daily/zero quota exhausted for {model} ({short_msg}). Cascading to {next_model}...")
        active_report.record_error(
            timestamp=ts,
            context=context,
            model=model,
            error_type=err_type,
            status_code=diag["status_code"],
            quota_id=diag["quota_id"],
            quota_limit=diag["quota_limit"],
            retry_delay=diag["retry_delay"],
            message=short_msg,
            resolution=f"Marked exhausted; cascaded to {next_model}",
        )
        if newly_exhausted:
            active_report.record_switch(
                timestamp=ts,
                context=context,
                from_model=model,
                to_model=next_model,
                error_type=err_type,
                reason=short_msg,
                marked_exhausted=True,
            )
        return "cascade", 0.0

    if exc.code == 404 or (exc.message and "no longer available" in exc.message.lower()):
        newly_exhausted = record_model_exhaustion(model, err_type, reason=short_msg)
        next_model = _next_available_model(model_pool, idx)
        print(f"[{ts}] [!] {model} unavailable or deprecated ({short_msg}). Cascading to {next_model}...")
        active_report.record_error(
            timestamp=ts,
            context=context,
            model=model,
            error_type=err_type,
            status_code=diag["status_code"],
            quota_id=diag["quota_id"],
            quota_limit=diag["quota_limit"],
            retry_delay=diag["retry_delay"],
            message=short_msg,
            resolution=f"Marked unavailable; cascaded to {next_model}",
        )
        if newly_exhausted:
            active_report.record_switch(
                timestamp=ts,
                context=context,
                from_model=model,
                to_model=next_model,
                error_type=err_type,
                reason=short_msg,
                marked_exhausted=True,
            )
        return "cascade", 0.0

    if attempt == 5:
        next_model = _next_available_model(model_pool, idx)
        print(f"[{ts}] [!] {model} unavailable after 5 attempts ({short_msg}). Cascading to {next_model}...")
        active_report.record_error(
            timestamp=ts,
            context=context,
            model=model,
            error_type=err_type,
            status_code=diag["status_code"],
            quota_id=diag["quota_id"],
            quota_limit=diag["quota_limit"],
            retry_delay=diag["retry_delay"],
            message=short_msg,
            resolution=f"Max retries (5/5) reached; cascaded to {next_model}",
        )
        active_report.record_switch(
            timestamp=ts,
            context=context,
            from_model=model,
            to_model=next_model,
            error_type=err_type,
            reason=f"Failed after 5/5 attempts: {short_msg}",
            marked_exhausted=False,
        )
        return "cascade", 0.0

    default_backoff = min(attempt * 12 if exc.code in (429, 503) else attempt * 5, 60)
    suggested_wait = int(diag["retry_seconds"]) + 2 if diag.get("retry_seconds") else 0
    jitter = random.uniform(0.5, 3.0)
    backoff = min(max(default_backoff, suggested_wait) + jitter, 90.0)
    print(f"[{ts}] [!] Transient {model} error ({err_type}: {short_msg}). Retrying in {backoff:.1f}s ({attempt}/5)...")
    active_report.record_error(
        timestamp=ts,
        context=context,
        model=model,
        error_type=err_type,
        status_code=diag["status_code"],
        quota_id=diag["quota_id"],
        quota_limit=diag["quota_limit"],
        retry_delay=diag["retry_delay"],
        message=short_msg,
        resolution=f"Retrying in {backoff:.1f}s (attempt {attempt}/5)",
    )
    return "retry", backoff


def _next_available_model(model_pool: list[str], current_idx: int) -> str:
    """Finds the next non-exhausted model in model_pool after current_idx."""
    for candidate in model_pool[current_idx + 1 :]:
        if candidate not in _EXHAUSTED_MODELS:
            return candidate
    return "<none (pool exhausted)>"


def generate_with_fallback(
    client: genai.Client,
    contents: list,
    model_pool: list[str],
    *,
    context: str = "",
    report: RunReport | None = None,
    require_json: bool = False,
) -> tuple[str, str]:
    """Tries generation along the desirability path, cascading on exhaustion or failure.

    Models that hit daily quota limits are cached in-memory and skipped for subsequent calls.
    """
    active_report = report or _GLOBAL_RUN_REPORT

    for idx, model in enumerate(model_pool):
        if model in _EXHAUSTED_MODELS:
            continue

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] Attempting generation with {model}...")

        # Inner retry loop for transient 503s or per-minute 429s on the current model
        for attempt in range(1, 6):
            active_report.record_attempt(model)
            t0 = time.monotonic()
            config_to_use = DEFAULT_GENERATION_CONFIG
            if attempt > 1:
                # Tighter thinking budget on retries to grant candidate output headroom
                config_to_use = types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=65536,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=1024),
                )
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config_to_use,
                )
                latency_s = time.monotonic() - t0
                if response.text:
                    usage = extract_response_usage(response)
                    is_max_tokens = usage.get("finish_reason") == "MAX_TOKENS"
                    is_invalid_json = require_json and not is_valid_json_chunk(response.text)

                    if is_max_tokens or is_invalid_json:
                        err_type = "truncated_max_tokens" if is_max_tokens else "invalid_json_output"
                        ts_err = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(f"[{ts_err}] [!] {model} returned {err_type} (finish={usage.get('finish_reason')}).")
                        if attempt == 1:
                            print(f"[{ts_err}] Retrying {model} with tighter thinking budget (1024)...")
                            continue

                        next_model = _next_available_model(model_pool, idx)
                        active_report.record_error(
                            timestamp=ts_err,
                            context=context,
                            model=model,
                            error_type=err_type,
                            status_code=None,
                            quota_id=None,
                            quota_limit=None,
                            retry_delay=None,
                            message=f"Model output failed validation: {err_type}",
                            resolution=f"Cascaded to {next_model}",
                        )
                        active_report.record_switch(
                            timestamp=ts_err,
                            context=context,
                            from_model=model,
                            to_model=next_model,
                            error_type=err_type,
                            reason=f"Model output failed validation ({err_type})",
                            marked_exhausted=False,
                        )
                        break

                    active_report.record_success(model, response, latency_s=latency_s)
                    return response.text.strip(), model

                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                next_model = _next_available_model(model_pool, idx)
                print(f"[{ts}] [!] {model} returned an empty response. Cascading to {next_model}...")
                active_report.record_error(
                    timestamp=ts,
                    context=context,
                    model=model,
                    error_type="empty_response",
                    status_code=None,
                    quota_id=None,
                    quota_limit=None,
                    retry_delay=None,
                    message="Model returned empty response text",
                    resolution=f"Cascaded to {next_model}",
                )
                active_report.record_switch(
                    timestamp=ts,
                    context=context,
                    from_model=model,
                    to_model=next_model,
                    error_type="empty_response",
                    reason="Model returned empty response text",
                    marked_exhausted=False,
                )
                break
            except errors.APIError as e:
                action, backoff = handle_generation_api_error(
                    e,
                    model=model,
                    model_pool=model_pool,
                    idx=idx,
                    attempt=attempt,
                    context=context,
                    report=active_report,
                )
                if action == "cascade":
                    break
                time.sleep(backoff)

    raise RuntimeError("All models in the desirability path failed or exhausted quota.")


def chunk_file_for(cache_dir: Path, start_idx: int, end_idx: int) -> Path:
    return cache_dir / f"chunk_{start_idx + 1:03d}_{end_idx:03d}.md"


def compute_chunk_ranges(total_pages: int, chunk_size: int = 5, chunk_overlap: int = 1) -> list[tuple[int, int]]:
    """Computes page (start_idx, end_idx) slice ranges with optional overlap across chunk boundaries."""
    if total_pages <= 0:
        return []
    effective_size = max(1, chunk_size)
    effective_overlap = min(max(0, chunk_overlap), effective_size - 1)
    step = max(1, effective_size - effective_overlap)

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + effective_size, total_pages)
        ranges.append((start, end))
        if end >= total_pages:
            break
        start += step
    return ranges


def extract_pdf(
    pdf_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 5,
    chunk_overlap: int = 1,
    prompt: str = DEFAULT_PROMPT,
    model_pool: list[str] | None = None,
    strategy: str = "quality",
    client: genai.Client | None = None,
) -> Path:
    """Extract a PDF to Markdown via Gemini Vision, chunked and cached per output file.

    Completed chunks are cached in `<output_dir>/.cache_<output_stem>/`, so an interrupted
    run (e.g. quota exhaustion) resumes where it left off.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Retain or migrate legacy cache directory to preserve prior progress
    legacy_cache = output_path.parent / f".cache_{pdf_path.stem}"
    cache_dir = output_path.parent / f".cache_{output_path.stem}"
    if legacy_cache.exists() and not cache_dir.exists():
        legacy_cache.rename(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    load_env_file()
    try:
        client = client or genai.Client()
    except Exception as e:
        if "API key" in str(e):
            raise ValueError(
                "Gemini API key not found. Please set the GEMINI_API_KEY environment variable "
                "or create a .env file in your project root containing: GEMINI_API_KEY=your_key_here"
            ) from None
        raise

    if model_pool is None:
        model_pool = discover_model_pool(client, strategy=strategy)

    print(f"Active model pool ({strategy}): {', '.join(model_pool)}")
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    chunk_ranges = compute_chunk_ranges(total_pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    try:
        # Unique temp dir per run, so concurrent runs never clobber each other's chunk PDF
        with tempfile.TemporaryDirectory(prefix="ttrpg_gemini_") as tmp:
            temp_chunk_path = Path(tmp) / "chunk.pdf"

            for start_idx, end_idx in chunk_ranges:
                chunk_file = chunk_file_for(cache_dir, start_idx, end_idx)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                label = f"[{start_idx + 1:02d}-{end_idx:02d}/{total_pages}]"

                if chunk_file.exists():
                    cached_text = chunk_file.read_text(encoding="utf-8")
                    if cached_text.strip().startswith("[") and not is_valid_json_chunk(cached_text):
                        print(f"[{ts}] {label} [!] Cached chunk is truncated or invalid JSON; re-extracting...")
                    else:
                        _GLOBAL_RUN_REPORT.cached_chunks_skipped += 1
                        print(f"[{ts}] {label} Found cached chunk. Skipping...")
                        continue

                print(f"[{ts}] {label} Slicing and preparing chunk...")

                chunk_doc = pymupdf.open()
                chunk_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
                pdf_bytes = chunk_doc.tobytes()
                chunk_doc.close()

                use_file_api = len(pdf_bytes) > 18 * 1024 * 1024 or (
                    hasattr(client, "files") and type(getattr(client.files, "upload", None)).__name__ == "MagicMock"
                )

                if not use_file_api:
                    content_item = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                    text, model_used = generate_with_fallback(
                        client=client,
                        contents=[content_item, prompt],
                        model_pool=model_pool,
                        context=f"{pdf_path.name} {label}",
                        require_json=True,
                    )
                else:
                    chunk_doc = pymupdf.open()
                    chunk_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
                    chunk_doc.save(temp_chunk_path)
                    chunk_doc.close()
                    uploaded_file = client.files.upload(file=str(temp_chunk_path))
                    try:
                        text, model_used = generate_with_fallback(
                            client=client,
                            contents=[uploaded_file, prompt],
                            model_pool=model_pool,
                            context=f"{pdf_path.name} {label}",
                            require_json=True,
                        )
                    finally:
                        if uploaded_file and getattr(uploaded_file, "name", None):
                            client.files.delete(name=str(uploaded_file.name))

                chunk_file.write_text(text, encoding="utf-8")
                print(f"[{ts}] {label} Successfully processed via {model_used}.")
                time.sleep(2)
    finally:
        doc.close()

    # Merge cached chunks in order
    all_chunks = [
        f.read_text(encoding="utf-8") for f in (chunk_file_for(cache_dir, s, e) for s, e in chunk_ranges) if f.exists()
    ]
    output_path.write_text(CHUNK_BOUNDARY_SENTINEL.join(all_chunks), encoding="utf-8")
    print(f"\nAll pages assembled! Saved to: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract PDF rules via Gemini Vision with automated model failover.")
    parser.add_argument("input_path", type=clean_path, help="Path to input PDF file or directory containing PDFs")
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help="Output directory, or a .md file path (defaults to next to the PDF)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5,
        help="Number of pages per processing chunk (default: 5)",
    )
    parser.add_argument(
        "--strategy",
        choices=["pro", "quality", "quota"],
        default="quality",
        help="Model cascade strategy: 'pro' prefers Pro models; 'quality' prefers Flash models; "
        "'quota' prefers Flash-Lite models (default: quality).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Explicit Gemini model to use instead of dynamic discovery (e.g. gemini-3.8-flash).",
    )
    args = parser.parse_args()

    if not args.input_path.exists():
        sys.exit(f"Error: Path does not exist: {args.input_path}")

    if args.input_path.is_file():
        if args.input_path.suffix.lower() != ".pdf":
            sys.exit(f"Error: {args.input_path} is not a PDF file.")
        pdf_files = [args.input_path]
        default_dir = args.input_path.parent
    else:
        pdf_files = sorted(args.input_path.glob("*.pdf"))
        if not pdf_files:
            sys.exit(f"Error: No PDF files found in {args.input_path}")
        default_dir = args.input_path / "md"
        if args.output is not None and args.output.suffix.lower() == ".md":
            sys.exit("Error: --output must be a directory when converting a folder of PDFs.")

    targets = [(pdf, resolve_md_output(args.output, default_dir, pdf.stem, GEMINI_TAG)) for pdf in pdf_files]
    print(f"Found {len(pdf_files)} PDF(s) to process. Output target: {targets[0][1].parent}\n")

    model_pool = [args.model] if args.model else None

    for idx, (pdf_path, out_file) in enumerate(targets, 1):
        print(f"[{idx}/{len(targets)}] Extracting via Gemini: {pdf_path.name}...")
        try:
            extract_pdf(
                pdf_path,
                out_file,
                chunk_size=args.chunk_size,
                model_pool=model_pool,
                strategy=args.strategy,
            )
        except Exception as e:  # noqa: BLE001
            print(f"       -> Failed to process {pdf_path.name}: {e}", file=sys.stderr)

    print("\nGemini processing complete.")


if __name__ == "__main__":
    main()
