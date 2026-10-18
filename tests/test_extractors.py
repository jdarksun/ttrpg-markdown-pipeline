from pathlib import Path
from unittest.mock import MagicMock

import pymupdf
import pytest
from google.genai import errors

from ttrpg_markdown_pipeline.extractors.docling import convert_pdf
from ttrpg_markdown_pipeline.extractors.gemini import (
    _EXHAUSTED_MODELS,
    _MODEL_POOL_CACHE,
    DEFAULT_DESIRABILITY_PATH,
    chunk_file_for,
    discover_model_pool,
    generate_with_fallback,
    is_daily_quota_exhausted,
)
from ttrpg_markdown_pipeline.extractors.gemini import (
    extract_pdf as gemini_extract_pdf,
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

    # Clear exhausted cache before test
    _EXHAUSTED_MODELS.clear()

    # First call: Model A exhausts daily quota; Model B succeeds
    quota_error = errors.APIError(429, {"error": {"message": "Resource exhausted: please retry in 12h"}})
    success_resp = MagicMock()
    success_resp.text = "Success on backup model"

    client.models.generate_content.side_effect = [quota_error, success_resp, success_resp]

    text, model = generate_with_fallback(client, ["content"], ["model-a", "model-b"])
    assert text == "Success on backup model"
    assert model == "model-b"
    assert "model-a" in _EXHAUSTED_MODELS

    # Second call: Model A is already in _EXHAUSTED_MODELS, so it immediately calls Model B without trying Model A
    client.models.generate_content.reset_mock()
    client.models.generate_content.return_value = success_resp
    text2, model2 = generate_with_fallback(client, ["chunk 2"], ["model-a", "model-b"])
    assert text2 == "Success on backup model"
    assert model2 == "model-b"
    assert client.models.generate_content.call_count == 1
    assert client.models.generate_content.call_args.kwargs["model"] == "model-b"


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


def test_discover_model_pool_strategies():
    mock_client = MagicMock()
    m1 = MagicMock(supported_actions=["generateContent"])
    m1.name = "models/gemini-2.5-flash"
    m2 = MagicMock(supported_actions=["generateContent"])
    m2.name = "models/gemini-3.8-flash"
    m3 = MagicMock(supported_actions=["generateContent"])
    m3.name = "models/gemini-3.5-flash-lite"
    m4 = MagicMock(supported_actions=["generateContent"])
    m4.name = "models/gemini-3.1-flash-lite"
    m_skip = MagicMock(supported_actions=["generateContent"])
    m_skip.name = "models/gemini-3.8-flash-tts"

    mock_client.models.list.return_value = [m1, m2, m3, m4, m_skip]

    _MODEL_POOL_CACHE.clear()
    quality_pool = discover_model_pool(mock_client, strategy="quality")
    assert quality_pool == [
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]

    _MODEL_POOL_CACHE.clear()
    quota_pool = discover_model_pool(mock_client, strategy="quota")
    assert quota_pool == [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.8-flash",
        "gemini-2.5-flash",
    ]


def test_discover_model_pool_fallback_on_error():
    mock_client = MagicMock()
    mock_client.models.list.side_effect = Exception("Network unreachable")

    _MODEL_POOL_CACHE.clear()
    pool = discover_model_pool(mock_client, strategy="quality")
    assert pool == DEFAULT_DESIRABILITY_PATH


def test_gemini_extract_pdf_creates_cache_and_output(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Page 1 rules")
    doc.new_page().insert_text((72, 72), "Page 2 rules")
    doc.save(pdf)
    doc.close()

    out_md = tmp_path / "output_dir" / "sample - GEMINI.md"

    mock_client = MagicMock()
    mock_upload = MagicMock()
    mock_upload.name = "files/test_file_123"
    mock_client.files.upload.return_value = mock_upload

    mock_resp = MagicMock()
    mock_resp.text = "Extracted Markdown Chunk"
    mock_client.models.generate_content.return_value = mock_resp

    result = gemini_extract_pdf(
        pdf_path=pdf,
        output_path=out_md,
        chunk_size=1,
        client=mock_client,
        model_pool=["gemini-3.8-flash"],
    )

    assert result == out_md
    assert out_md.exists()
    assert "Extracted Markdown Chunk" in out_md.read_text(encoding="utf-8")

    cache_dir = tmp_path / "output_dir" / f".cache_{out_md.stem}"
    assert cache_dir.exists()
    assert (cache_dir / "chunk_001_001.md").exists()
    assert (cache_dir / "chunk_002_002.md").exists()


def test_gemini_main_batch_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ttrpg_markdown_pipeline.extractors.gemini import main as gemini_main

    pdf_dir = tmp_path / "chapters"
    pdf_dir.mkdir()
    pdf1 = pdf_dir / "01-Chapter.pdf"
    pdf2 = pdf_dir / "02-Chapter.pdf"

    for p in (pdf1, pdf2):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Content")
        doc.save(p)
        doc.close()

    out_dir = tmp_path / "output"

    called_paths = []

    def mock_extract(pdf_path, output_path, **kwargs):
        called_paths.append((pdf_path, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("Extracted", encoding="utf-8")
        return output_path

    monkeypatch.setattr("ttrpg_markdown_pipeline.extractors.gemini.extract_pdf", mock_extract)
    monkeypatch.setattr("sys.argv", ["ttrpg-gemini", str(pdf_dir), "-o", str(out_dir)])

    gemini_main()

    assert len(called_paths) == 2
    assert called_paths[0][0] == pdf1
    assert called_paths[0][1] == out_dir / "01-Chapter - GEMINI.md"
    assert called_paths[1][0] == pdf2
    assert called_paths[1][1] == out_dir / "02-Chapter - GEMINI.md"
