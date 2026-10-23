"""Asynchronous Gemini API layer for batch vision extraction."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors

from ttrpg_markdown_pipeline.common import load_env_file
from ttrpg_markdown_pipeline.extractors.gemini import (
    _EXHAUSTED_MODELS,
    DEFAULT_GENERATION_CONFIG,
    RunReport,
    _next_available_model,
    chunk_file_for,
    compute_chunk_ranges,
    discover_model_pool,
    get_run_report,
    is_daily_quota_exhausted,
    parse_api_error_diagnostics,
)
from ttrpg_markdown_pipeline.rules.cosmere import DEFAULT_PROMPT


async def generate_with_fallback_async(
    client: genai.Client,
    contents: list,
    model_pool: list[str],
    *,
    context: str = "",
    report: RunReport | None = None,
) -> tuple[str, str]:
    """Tries async generation along the desirability path, cascading on exhaustion or failure."""
    active_report = report or get_run_report()

    for idx, model in enumerate(model_pool):
        if model in _EXHAUSTED_MODELS:
            continue

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] Attempting async generation with {model}...")

        for attempt in range(1, 6):
            active_report.record_attempt(model)
            t0 = time.monotonic()
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=DEFAULT_GENERATION_CONFIG,
                )
                latency_s = time.monotonic() - t0
                if response.text:
                    usage = active_report.record_success(model, response, latency_s=latency_s)
                    if usage["total_tokens"] > 0:
                        ts_done = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[{ts_done}] {context + ' ' if context else ''}Usage ({model}): "
                            f"prompt={usage['prompt_tokens']:,}, output={usage['candidates_tokens']:,}, "
                            f"thoughts={usage['thoughts_tokens']:,}, total={usage['total_tokens']:,} "
                            f"tokens | finish={usage['finish_reason']} | {latency_s:.1f}s"
                        )
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
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                diag = parse_api_error_diagnostics(e)
                err_type = diag["error_type"]
                short_msg = diag["short_message"]

                if is_daily_quota_exhausted(e):
                    _EXHAUSTED_MODELS.add(model)
                    next_model = _next_available_model(model_pool, idx)
                    print(
                        f"[{ts}] [!] Daily/zero quota exhausted for {model} ({short_msg}). Cascading to {next_model}..."
                    )
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
                    active_report.record_switch(
                        timestamp=ts,
                        context=context,
                        from_model=model,
                        to_model=next_model,
                        error_type=err_type,
                        reason=short_msg,
                        marked_exhausted=True,
                    )
                    break

                if e.code == 404 or (e.message and "no longer available" in e.message.lower()):
                    _EXHAUSTED_MODELS.add(model)
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
                    active_report.record_switch(
                        timestamp=ts,
                        context=context,
                        from_model=model,
                        to_model=next_model,
                        error_type=err_type,
                        reason=short_msg,
                        marked_exhausted=True,
                    )
                    break

                if attempt == 5:
                    next_model = _next_available_model(model_pool, idx)
                    print(
                        f"[{ts}] [!] {model} unavailable after 5 attempts ({short_msg}). Cascading to {next_model}..."
                    )
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
                    break

                default_backoff = min(attempt * 12 if e.code in (429, 503) else attempt * 5, 60)
                suggested_wait = int(diag["retry_seconds"]) + 2 if diag["retry_seconds"] else 0
                backoff = min(max(default_backoff, suggested_wait), 90)
                print(
                    f"[{ts}] [!] Transient {model} error ({err_type}: {short_msg}). "
                    f"Retrying in {backoff}s ({attempt}/5)..."
                )
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
                    resolution=f"Retrying in {backoff}s (attempt {attempt}/5)",
                )
                await asyncio.sleep(backoff)

    raise RuntimeError("All models in the desirability path failed or exhausted quota.")


async def _process_chunk_async(
    client: genai.Client,
    pdf_path: Path,
    start_idx: int,
    end_idx: int,
    total_pages: int,
    cache_dir: Path,
    prompt: str,
    model_pool: list[str],
    semaphore: asyncio.Semaphore,
) -> str:
    """Processes a single slice of pages asynchronously with caching and concurrency control."""
    chunk_file = chunk_file_for(cache_dir, start_idx, end_idx)
    label = f"[{start_idx + 1:02d}–{end_idx:02d}/{total_pages}]"

    if chunk_file.exists():
        get_run_report().cached_chunks_skipped += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {label} Found cached chunk. Skipping...")
        return chunk_file.read_text(encoding="utf-8")

    async with semaphore:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {label} Slicing and preparing chunk...")

        # Slice PDF slice to temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_f:
            temp_chunk_path = Path(tmp_f.name)

        try:
            # Synchronous PDF slicing via pymupdf
            doc = pymupdf.open(pdf_path)
            chunk_doc = pymupdf.open()
            chunk_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
            chunk_doc.save(temp_chunk_path)
            chunk_doc.close()
            doc.close()

            # Upload file via modern SDK client.files.upload with retry for transient 503/network errors
            uploaded_file = None
            for upload_attempt in range(1, 4):
                try:
                    uploaded_file = await asyncio.to_thread(client.files.upload, file=str(temp_chunk_path))
                    break
                except Exception as upload_err:
                    if upload_attempt == 3:
                        raise
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    backoff = upload_attempt * 3
                    print(f"[{ts}] {label} Upload transient error ({upload_err}). Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)

            try:
                text, model_used = await generate_with_fallback_async(
                    client=client,
                    contents=[uploaded_file, prompt],
                    model_pool=model_pool,
                    context=f"{pdf_path.name} {label}",
                )
                chunk_file.write_text(text, encoding="utf-8")
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] {label} Successfully processed via {model_used}.")
                return text
            finally:
                if uploaded_file and uploaded_file.name:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(client.files.delete, name=uploaded_file.name)
        finally:
            if temp_chunk_path.exists():
                temp_chunk_path.unlink()


async def extract_pdf_async(
    pdf_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 5,
    chunk_overlap: int = 1,
    prompt: str = DEFAULT_PROMPT,
    model_pool: list[str] | None = None,
    strategy: str = "quality",
    max_concurrency: int = 3,
    client: genai.Client | None = None,
) -> Path:
    """Asynchronously extracts a PDF with concurrent chunk processing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = output_path.parent / f".cache_{output_path.stem}"
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
    doc.close()

    chunk_ranges = compute_chunk_ranges(total_pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    semaphore = asyncio.Semaphore(max_concurrency)

    tasks = [
        _process_chunk_async(
            client=client,
            pdf_path=pdf_path,
            start_idx=s,
            end_idx=e,
            total_pages=total_pages,
            cache_dir=cache_dir,
            prompt=prompt,
            model_pool=model_pool,
            semaphore=semaphore,
        )
        for s, e in chunk_ranges
    ]

    await asyncio.gather(*tasks)

    # Assemble cached chunks in order
    all_chunks = [
        f.read_text(encoding="utf-8") for f in (chunk_file_for(cache_dir, s, e) for s, e in chunk_ranges) if f.exists()
    ]
    output_path.write_text("\n\n---\n\n".join(all_chunks), encoding="utf-8")
    print(f"\nAll pages assembled! Saved to: {output_path}")
    return output_path
