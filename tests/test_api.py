"""Tests for async Gemini API extraction."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pymupdf
import pytest
from google.genai import errors

from ttrpg_markdown_pipeline.extractors.api import (
    extract_pdf_async,
    generate_with_fallback_async,
)
from ttrpg_markdown_pipeline.extractors.gemini import _EXHAUSTED_MODELS


@pytest.mark.anyio
async def test_generate_with_fallback_async_success():
    _EXHAUSTED_MODELS.clear()
    client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Async response content"
    client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    text, model = await generate_with_fallback_async(client, ["content"], ["model-a", "model-b"])
    assert text == "Async response content"
    assert model == "model-a"


@pytest.mark.anyio
async def test_generate_with_fallback_async_cascades_on_quota():
    client = MagicMock()
    _EXHAUSTED_MODELS.clear()

    quota_err = errors.APIError(429, {"error": {"message": "Resource exhausted: please retry in 12h"}})
    mock_resp = MagicMock()
    mock_resp.text = "Model B async success"

    client.aio.models.generate_content = AsyncMock(side_effect=[quota_err, mock_resp])

    text, model = await generate_with_fallback_async(client, ["content"], ["model-a", "model-b"])
    assert text == "Model B async success"
    assert model == "model-b"
    assert "model-a" in _EXHAUSTED_MODELS


@pytest.mark.anyio
async def test_extract_pdf_async(tmp_path: Path):
    pdf = tmp_path / "sample_async.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Page 1 async text")
    doc.new_page().insert_text((72, 72), "Page 2 async text")
    doc.save(pdf)
    doc.close()

    out_md = tmp_path / "output_dir" / "sample - GEMINI.md"

    client = MagicMock()
    mock_upload = MagicMock()
    mock_upload.name = "files/async_file_123"
    client.files.upload = MagicMock(return_value=mock_upload)
    client.files.delete = MagicMock()

    mock_resp = MagicMock()
    mock_resp.text = '[\n  {"name": "Async Talent", "type": "talent"}\n]'
    client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    res = await extract_pdf_async(
        pdf_path=pdf,
        output_path=out_md,
        chunk_size=1,
        client=client,
        model_pool=["gemini-3.8-flash"],
        max_concurrency=2,
    )

    assert res == out_md
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "Async Talent" in content


@pytest.mark.anyio
async def test_generate_with_fallback_async_probe_locking():
    from ttrpg_markdown_pipeline.extractors.api import _VERIFIED_WORKING_MODELS

    _EXHAUSTED_MODELS.clear()
    _VERIFIED_WORKING_MODELS.clear()

    client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '[{"name": "Rule"}]'
    client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    text, model = await generate_with_fallback_async(client, ["content"], ["gemini-3.8-flash"], require_json=True)
    assert text == '[{"name": "Rule"}]'
    assert model == "gemini-3.8-flash"
    assert "gemini-3.8-flash" in _VERIFIED_WORKING_MODELS


@pytest.mark.anyio
async def test_adaptive_splitting_no_semaphore_deadlock(tmp_path: Path):
    """Verifies that adaptive chunk splitting with semaphore=1 does not deadlock."""
    from ttrpg_markdown_pipeline.extractors.api import _process_chunk_async

    pdf = tmp_path / "deadlock_test.pdf"
    doc = pymupdf.open()
    for i in range(4):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}")
    doc.save(pdf)
    doc.close()

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()

    client = MagicMock()

    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Full 4-page chunk failed across models")
        resp = MagicMock()
        if call_count == 2:
            resp.text = '```json\n[{"name": "Rule A", "type": "rule"}]\n```'
        else:
            resp.text = '```json\n[{"name": "Rule B", "type": "rule"}]\n```'
        return resp

    client.aio.models.generate_content = AsyncMock(side_effect=mock_generate)
    semaphore = asyncio.Semaphore(1)

    result_json = await _process_chunk_async(
        client=client,
        pdf_path=pdf,
        start_idx=0,
        end_idx=4,
        total_pages=4,
        cache_dir=cache_dir,
        prompt="test",
        model_pool=["gemini-3.8-flash"],
        semaphore=semaphore,
    )

    import json

    parsed = json.loads(result_json)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Rule A"
    assert parsed[1]["name"] == "Rule B"


@pytest.mark.anyio
async def test_max_tokens_does_not_increment_calls_succeeded():
    """Verifies that a MAX_TOKENS finish reason does not falsely count as a successful call."""
    from ttrpg_markdown_pipeline.extractors.gemini import RunReport

    client = MagicMock()
    report = RunReport()

    mock_resp_max = MagicMock()
    mock_resp_max.text = '[{"name": "Incomplete Rule"'
    candidate_max = MagicMock()
    candidate_max.finish_reason = "MAX_TOKENS"
    mock_resp_max.candidates = [candidate_max]

    mock_resp_ok = MagicMock()
    mock_resp_ok.text = '[{"name": "Complete Rule", "type": "rule"}]'
    candidate_ok = MagicMock()
    candidate_ok.finish_reason = "STOP"
    mock_resp_ok.candidates = [candidate_ok]

    # Attempt 1: MAX_TOKENS (retried with tighter thinking) -> Attempt 2: OK
    client.aio.models.generate_content = AsyncMock(side_effect=[mock_resp_max, mock_resp_ok])

    text, model = await generate_with_fallback_async(
        client=client,
        contents=["test"],
        model_pool=["gemini-3.8-flash"],
        report=report,
        require_json=True,
    )

    assert model == "gemini-3.8-flash"
    assert "Complete Rule" in text
    stats = report.model_usage["gemini-3.8-flash"]
    assert stats.calls_attempted == 2
    assert stats.calls_succeeded == 1
