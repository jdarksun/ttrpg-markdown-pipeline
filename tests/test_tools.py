from pathlib import Path

import pymupdf
import pytest

from ttrpg_markdown_pipeline.tools.inspect_glyphs import find_glyphs


def test_inspect_glyphs_runs_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    pdf = tmp_path / "test_glyphs.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Actions () are spent on turns.")
    doc.save(pdf)
    doc.close()

    find_glyphs(str(pdf), search="Actions (")
    # Verify no unhandled crash occurred
    captured = capsys.readouterr()
    assert captured.err == ""

