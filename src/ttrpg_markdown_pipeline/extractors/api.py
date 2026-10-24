"""Asynchronous Gemini API layer for batch vision extraction."""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors, types

from ttrpg_markdown_pipeline.common import load_env_file
from ttrpg_markdown_pipeline.extractors.gemini import (
    _EXHAUSTED_MODELS,
    CHUNK_BOUNDARY_SENTINEL,
    MAX_INLINE_PDF_BYTES,
    RunReport,
    build_generation_config,
    chunk_file_for,
    compute_chunk_ranges,
    discover_model_pool,
    get_run_report,
    handle_generation_api_error,
    is_valid_json_chunk,
    load_persisted_quota_state,
    parse_json_chunk,
    validate_and_record_response,
)
from ttrpg_markdown_pipeline.rules.cosmere import DEFAULT_PROMPT

_VERIFIED_WORKING_MODELS: set[str] = set()
_MODEL_PROBE_LOCKS: dict[str, asyncio.Lock] = {}


async def _try_model_with_retries_async(
    client: genai.Client,
    model: str,
    contents: list,
    model_pool: list[str],
    idx: int,
    *,
    context: str = "",
    report: RunReport | None = None,
    require_json: bool = False,
) -> tuple[str, str] | None:
    """Runs retry loop for a single model, returning (text, model) on success or None on cascade."""
    active_report = report or get_run_report()
    for attempt in range(1, 6):
        active_report.record_attempt(model)
        t0 = time.monotonic()
        config_to_use = build_generation_config(attempt)
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config_to_use,
            )
            latency_s = time.monotonic() - t0
            action, text, _ = validate_and_record_response(
                response=response,
                model=model,
                latency_s=latency_s,
                attempt=attempt,
                model_pool=model_pool,
                idx=idx,
                require_json=require_json,
                report=active_report,
                context=context,
            )
            if action == "ok" and text is not None:
                return text, model
            if action == "retry":
                continue
            if action == "cascade":
                return None
        except errors.APIError as e:
            err_action, backoff = handle_generation_api_error(
                e,
                model=model,
                model_pool=model_pool,
                idx=idx,
                attempt=attempt,
                context=context,
                report=active_report,
            )
            if err_action == "cascade":
                return None
            await asyncio.sleep(backoff)
    return None


async def generate_with_fallback_async(
    client: genai.Client,
    contents: list,
    model_pool: list[str],
    *,
    context: str = "",
    report: RunReport | None = None,
    require_json: bool = False,
) -> tuple[str, str]:
    """Tries async generation along the desirability path, cascading on exhaustion or failure."""
    load_persisted_quota_state()
    active_report = report or get_run_report()

    for idx, model in enumerate(model_pool):
        if model in _EXHAUSTED_MODELS:
            continue

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] Attempting async generation with {model}...")

        # Guard unverified models with single-flight probe lock across concurrent workers
        if model not in _VERIFIED_WORKING_MODELS:
            probe_lock = _MODEL_PROBE_LOCKS.setdefault(model, asyncio.Lock())
            async with probe_lock:
                if model in _EXHAUSTED_MODELS:
                    continue
                if model not in _VERIFIED_WORKING_MODELS:
                    res = await _try_model_with_retries_async(
                        client=client,
                        model=model,
                        contents=contents,
                        model_pool=model_pool,
                        idx=idx,
                        context=context,
                        report=active_report,
                        require_json=require_json,
                    )
                    if res is not None:
                        _VERIFIED_WORKING_MODELS.add(model)
                        return res
                    continue

        # Model is verified (or verified while waiting on lock); run concurrently
        res = await _try_model_with_retries_async(
            client=client,
            model=model,
            contents=contents,
            model_pool=model_pool,
            idx=idx,
            context=context,
            report=active_report,
            require_json=require_json,
        )
        if res is not None:
            return res

    raise RuntimeError("All models in the desirability path failed or exhausted quota.")


async def _execute_single_slice_async(
    client: genai.Client,
    pdf_path: Path,
    start_idx: int,
    end_idx: int,
    total_pages: int,
    prompt: str,
    model_pool: list[str],
    semaphore: asyncio.Semaphore,
    max_inline_bytes: int = MAX_INLINE_PDF_BYTES,
) -> tuple[str, str]:
    """Acquires semaphore and executes generation for a single PDF slice."""
    label = f"[{start_idx + 1:02d}-{end_idx:02d}/{total_pages}]"
    async with semaphore:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {label} Slicing and preparing chunk...")

        doc = pymupdf.open(pdf_path)
        chunk_doc = pymupdf.open()
        chunk_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
        pdf_bytes = chunk_doc.tobytes()
        chunk_doc.close()
        doc.close()

        use_file_api = len(pdf_bytes) > max_inline_bytes

        if not use_file_api:
            content_item = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
            return await generate_with_fallback_async(
                client=client,
                contents=[content_item, prompt],
                model_pool=model_pool,
                context=f"{pdf_path.name} {label}",
                require_json=True,
            )
        else:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_f:
                temp_chunk_path = Path(tmp_f.name)
            try:
                temp_chunk_path.write_bytes(pdf_bytes)
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
                    return await generate_with_fallback_async(
                        client=client,
                        contents=[uploaded_file, prompt],
                        model_pool=model_pool,
                        context=f"{pdf_path.name} {label}",
                        require_json=True,
                    )
                finally:
                    if uploaded_file and getattr(uploaded_file, "name", None):
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(client.files.delete, name=str(uploaded_file.name))
            finally:
                if temp_chunk_path.exists():
                    temp_chunk_path.unlink()


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
    max_inline_bytes: int = MAX_INLINE_PDF_BYTES,
) -> str:
    """Processes a single slice of pages asynchronously with caching and concurrency control."""
    chunk_file = chunk_file_for(cache_dir, start_idx, end_idx)
    label = f"[{start_idx + 1:02d}-{end_idx:02d}/{total_pages}]"

    if chunk_file.exists():
        cached_text = chunk_file.read_text(encoding="utf-8")
        if cached_text.strip().startswith(("[", "```")) and not is_valid_json_chunk(cached_text):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] {label} [!] Cached chunk is truncated or invalid JSON; re-extracting...")
        else:
            get_run_report().cached_chunks_skipped += 1
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] {label} Found cached chunk. Skipping...")
            return cached_text

    try:
        text, model_used = await _execute_single_slice_async(
            client=client,
            pdf_path=pdf_path,
            start_idx=start_idx,
            end_idx=end_idx,
            total_pages=total_pages,
            prompt=prompt,
            model_pool=model_pool,
            semaphore=semaphore,
            max_inline_bytes=max_inline_bytes,
        )
        chunk_file.write_text(text, encoding="utf-8")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {label} Successfully processed via {model_used}.")
        return text
    except RuntimeError as run_err:
        if end_idx - start_idx >= 3:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{ts}] {label} [!] Chunk failed across models ({run_err}). "
                f"Adaptive-splitting pages {start_idx + 1}-{end_idx} in half..."
            )
            mid_idx = (start_idx + end_idx) // 2
            text_a = await _process_chunk_async(
                client=client,
                pdf_path=pdf_path,
                start_idx=start_idx,
                end_idx=mid_idx,
                total_pages=total_pages,
                cache_dir=cache_dir,
                prompt=prompt,
                model_pool=model_pool,
                semaphore=semaphore,
                max_inline_bytes=max_inline_bytes,
            )
            text_b = await _process_chunk_async(
                client=client,
                pdf_path=pdf_path,
                start_idx=mid_idx,
                end_idx=end_idx,
                total_pages=total_pages,
                cache_dir=cache_dir,
                prompt=prompt,
                model_pool=model_pool,
                semaphore=semaphore,
                max_inline_bytes=max_inline_bytes,
            )
            items_a = parse_json_chunk(text_a)
            items_b = parse_json_chunk(text_b)
            merged_json = json.dumps(items_a + items_b, indent=2)
            chunk_file.write_text(merged_json, encoding="utf-8")
            return merged_json
        raise


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
    max_inline_bytes: int = MAX_INLINE_PDF_BYTES,
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
            max_inline_bytes=max_inline_bytes,
        )
        for s, e in chunk_ranges
    ]

    await asyncio.gather(*tasks)

    # Assemble cached chunks in order
    all_chunks = [
        f.read_text(encoding="utf-8") for f in (chunk_file_for(cache_dir, s, e) for s, e in chunk_ranges) if f.exists()
    ]
    output_path.write_text(CHUNK_BOUNDARY_SENTINEL.join(all_chunks), encoding="utf-8")
    print(f"\nAll pages assembled! Saved to: {output_path}")
    return output_path
