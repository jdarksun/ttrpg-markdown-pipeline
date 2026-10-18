from collections.abc import Generator
from pathlib import Path

import pymupdf
import pytest


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
