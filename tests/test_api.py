"""Tests for async Gemini API extraction."""

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
