from collections.abc import Generator
from pathlib import Path

import pymupdf
import pytest

import ttrpg_markdown_pipeline.extractors.gemini as gemini_mod
from ttrpg_markdown_pipeline.extractors.api import _MODEL_PROBE_LOCKS, _VERIFIED_WORKING_MODELS
from ttrpg_markdown_pipeline.extractors.gemini import _EXHAUSTED_MODELS


@pytest.fixture(autouse=True)
def isolate_quota_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Isolates quota state and resets mutable model sets across tests."""
    test_state_file = tmp_path / ".gemini_quota_state.json"
    monkeypatch.setattr(gemini_mod, "QUOTA_STATE_FILE", test_state_file)
    _EXHAUSTED_MODELS.clear()
    _VERIFIED_WORKING_MODELS.clear()
    _MODEL_PROBE_LOCKS.clear()
    yield
    _EXHAUSTED_MODELS.clear()
    _VERIFIED_WORKING_MODELS.clear()
    _MODEL_PROBE_LOCKS.clear()


@pytest.fixture
def sample_pdf_with_toc(tmp_path: Path) -> Generator[Path, None, None]:
    """Generates a synthetic 10-page master PDF with a 3-chapter TOC."""
    pdf_path = tmp_path / "Master_Rulebook.pdf"
    doc = pymupdf.open()
    for i in range(10):
        doc.new_page().insert_text((72, 72), f"Physical Page {i + 1}")

    toc = [
        [1, "Introduction", 1],  # Pages 1 to 2
        [1, "Chapter 4: Heroic Paths", 3],  # Pages 3 to 6
        [1, "Chapter 8: Combat Rules", 7],  # Pages 7 to 10
    ]
    doc.set_toc(toc)
    doc.save(pdf_path)
    doc.close()

    yield pdf_path


@pytest.fixture
def bare_pdf(tmp_path: Path) -> Generator[Path, None, None]:
    """Generates a synthetic 1-page PDF without a Table of Contents."""
    pdf_path = tmp_path / "Bare.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Single page content without TOC")
    doc.save(pdf_path)
    doc.close()

    yield pdf_path
