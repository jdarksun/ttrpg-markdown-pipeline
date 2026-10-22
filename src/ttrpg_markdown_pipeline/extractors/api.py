"""Asynchronous Gemini API layer for batch vision extraction."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from datetime import datetime
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors

from ttrpg_markdown_pipeline.common import load_env_file
from ttrpg_markdown_pipeline.extractors.gemini import (
    _EXHAUSTED_MODELS,
    chunk_file_for,
    discover_model_pool,
    is_daily_quota_exhausted,
)
from ttrpg_markdown_pipeline.rules.cosmere import DEFAULT_PROMPT


async def generate_with_fallback_async(
    client: genai.Client,
    contents: list,
    model_pool: list[str],
) -> tuple[str, str]:
    """Tries async generation along the desirability path, cascading on exhaustion or failure."""
    for model in model_pool:
        if model in _EXHAUSTED_MODELS:
            continue

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] Attempting async generation with {model}...")

        for attempt in range(1, 4):
            try:
                response = await client.aio.models.generate_content(model=model, contents=contents)
                if response.text:
                    return response.text.strip(), model
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [!] {model} returned an empty response. Cascading to next model...")
                break
            except errors.APIError as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if is_daily_quota_exhausted(e):
                    print(f"[{ts}] [!] Daily quota exhausted for {model}. Cascading to next model...")
                    _EXHAUSTED_MODELS.add(model)
                    break

                if e.code == 404 or (e.message and "no longer available" in e.message.lower()):
                    print(f"[{ts}] [!] {model} unavailable or deprecated ({e.code}). Cascading to next model...")
                    _EXHAUSTED_MODELS.add(model)
                    break

                if attempt == 3:
                    print(f"[{ts}] [!] {model} unavailable after 3 attempts ({e.code}: {e.message[:80]}). Cascading to next model...")
                    break

                backoff = attempt * 10 if e.code == 429 else attempt * 4
                print(f"[{ts}] [!] Transient {model} error ({e.code}: {e.message[:80]}). Retrying in {backoff}s (attempt {attempt}/3)...")
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
    chunk_size: int = 8,
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

    chunk_ranges = [(s, min(s + chunk_size, total_pages)) for s in range(0, total_pages, chunk_size)]
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
