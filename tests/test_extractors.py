from pathlib import Path
from unittest.mock import MagicMock

import pymupdf
import pytest
from google.genai import errors

from ttrpg_markdown_pipeline.extractors.docling import convert_pdf
from ttrpg_markdown_pipeline.extractors.gemini import (
    chunk_file_for,
    generate_with_fallback,
    is_daily_quota_exhausted,
)
from ttrpg_markdown_pipeline.extractors.pymupdf import extract_pdf


def test_is_daily_quota_exhausted():
    # Daily quota message variations
    assert is_daily_quota_exhausted(Exception("ResourceExhausted: please retry in 14h30m")) is True
    assert is_daily_quota_exhausted(Exception("Rate limit reached. Please retry in 1d")) is True

    # Transient errors (should not be considered daily exhaustion)
    assert is_daily_quota_exhausted(Exception("503 Service Unavailable: overloaded")) is False
    assert is_daily_quota_exhausted(Exception("400 Bad Request: invalid argument")) is False


def test_chunk_file_for(tmp_path: Path):
    assert chunk_file_for(tmp_path, 0, 8) == tmp_path / "chunk_001_008.md"
    assert chunk_file_for(tmp_path, 8, 16) == tmp_path / "chunk_009_016.md"
    assert chunk_file_for(tmp_path, 16, 21) == tmp_path / "chunk_017_021.md"


def test_generate_with_fallback_success():
    client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Generated markdown content"
    client.models.generate_content.return_value = mock_resp

    text, model = generate_with_fallback(client, ["content"], ["model-a", "model-b"])
    assert text == "Generated markdown content"
    assert model == "model-a"


def test_generate_with_fallback_cascades_on_daily_quota():
    client = MagicMock()

    # Model A exhausts daily quota; Model B succeeds
    quota_error = errors.APIError(429, {"error": {"message": "Resource exhausted: please retry in 12h"}})
    success_resp = MagicMock()
    success_resp.text = "Success on backup model"

    client.models.generate_content.side_effect = [quota_error, success_resp]

    text, model = generate_with_fallback(client, ["content"], ["model-a", "model-b"])
    assert text == "Success on backup model"
    assert model == "model-b"


def test_generate_with_fallback_all_fail_raises():
    client = MagicMock()
    quota_error = errors.APIError(429, {"error": {"message": "Resource exhausted: please retry in 12h"}})
    client.models.generate_content.side_effect = quota_error

    with pytest.raises(RuntimeError, match="All models in the desirability path failed"):
        generate_with_fallback(client, ["content"], ["model-a", "model-b"])


def test_docling_convert_pdf_skips_when_exists(tmp_path: Path):
    pdf = tmp_path / "chap.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    out = tmp_path / "chap - DOCLING.md"
    out.write_text("Existing markdown content", encoding="utf-8")

    mock_converter = MagicMock()
    # force=False skips calling converter.convert()
    res = convert_pdf(pdf, out, converter=mock_converter, force=False)
    assert res == out
    mock_converter.convert.assert_not_called()
    assert out.read_text(encoding="utf-8") == "Existing markdown content"


def test_pymupdf_extract_pdf(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample Rules Heading\nThis is rule text.")
    doc.save(pdf)
    doc.close()

    out = tmp_path / "sample.md"
    res = extract_pdf(pdf, out)
    assert res == out
    assert out.exists()
    assert "Sample Rules Heading" in out.read_text(encoding="utf-8")
