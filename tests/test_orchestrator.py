from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pymupdf
import pytest

from ttrpg_markdown_pipeline.orchestrator import (
    Chapter,
    LazyConverter,
    process_chapter,
    sanitize_filename,
    split_pdf_by_chapters,
)


def test_sanitize_filename():
    assert sanitize_filename('Chapter: "Combat" & Actions?') == "Chapter Combat & Actions"
    assert sanitize_filename("Path/To/File|Name*") == "PathToFileName"
    assert sanitize_filename("Chapter 1\n - The World\r\n") == "Chapter 1 - The World"
    assert sanitize_filename("Title\twith\n\nmultiple   spaces") == "Title with multiple spaces"


def test_split_pdf_by_chapters(sample_pdf_with_toc: Path, tmp_path: Path):
    split_dir = tmp_path / "PDF_Chapters"
    chapters = split_pdf_by_chapters(sample_pdf_with_toc, split_dir)

    assert len(chapters) == 3

    # Chapter 0 (Intro)
    assert chapters[0].path.name == "00-Introduction.pdf"
    assert len(pymupdf.open(chapters[0].path)) == 2
    assert chapters[0].mechanics is False

    # Chapter 1 (Heroic Paths) -> detected as mechanics, numbered 04
    assert chapters[1].path.name == "04-Chapter 4 - Heroic Paths.pdf"
    assert len(pymupdf.open(chapters[1].path)) == 4
    assert chapters[1].mechanics is True

    # Chapter 2 (Combat) -> detected as mechanics, numbered 08
    assert chapters[2].path.name == "08-Chapter 8 - Combat Rules.pdf"
    assert len(pymupdf.open(chapters[2].path)) == 4
    assert chapters[2].mechanics is True


def test_split_pdf_no_toc_raises_error(bare_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="No Table of Contents found"):
        split_pdf_by_chapters(bare_pdf, tmp_path / "split")


def test_lazy_converter():
    with patch("ttrpg_markdown_pipeline.orchestrator.DocumentConverter") as mock_conv_cls:
        lazy = LazyConverter()
        assert lazy._converter is None
        mock_conv_cls.assert_not_called()

        inst1 = lazy.get()
        assert inst1 is not None
        assert mock_conv_cls.call_count == 1

        inst2 = lazy.get()
        assert inst2 is inst1
        # Ensures DocumentConverter was only constructed once
        assert mock_conv_cls.call_count == 1


def test_process_chapter_narrative_routing(tmp_path: Path):
    pdf = tmp_path / "01-Lore.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    md_dir = tmp_path / "md"
    md_dir.mkdir()

    chap = Chapter(path=pdf, title="Lore", mechanics=False)
    converter = MagicMock()

    with (
        patch("ttrpg_markdown_pipeline.orchestrator.convert_pdf") as mock_convert,
        patch("ttrpg_markdown_pipeline.orchestrator.extract_pdf_async") as mock_extract_async,
        patch("ttrpg_markdown_pipeline.orchestrator.patch_file") as mock_patch,
    ):
        mock_convert.side_effect = lambda src, dst, **kwargs: dst.write_text("lore", encoding="utf-8") or dst

        final_md = process_chapter(chap, md_dir, converter, force=False, docling_only=False, chunk_size=8)

        assert final_md == md_dir / "01-Lore - DOCLING.md"
        mock_convert.assert_called_once()
        mock_extract_async.assert_not_called()
        mock_patch.assert_called_once_with(final_md)


def test_process_chapter_mechanics_routing(tmp_path: Path):
    pdf = tmp_path / "04-Paths.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    md_dir = tmp_path / "md"
    md_dir.mkdir()
    vault_dir = tmp_path / "okf_vault"

    chap = Chapter(path=pdf, title="Heroic Paths", mechanics=True)
    converter = MagicMock()

    with (
        patch("ttrpg_markdown_pipeline.orchestrator.convert_pdf") as mock_convert,
        patch("ttrpg_markdown_pipeline.orchestrator.extract_pdf_async", new_callable=AsyncMock) as mock_extract_async,
        patch("ttrpg_markdown_pipeline.orchestrator.shred_chapter") as mock_shred,
        patch("ttrpg_markdown_pipeline.orchestrator.patch_file") as mock_patch,
    ):
        mock_convert.side_effect = lambda src, dst, **kwargs: dst.write_text("docling", encoding="utf-8") or dst
        mock_extract_async.side_effect = lambda src, dst, **kwargs: dst.write_text("gemini", encoding="utf-8") or dst
        mock_shred.return_value = [vault_dir / "sample.md"]

        final_md = process_chapter(
            chap,
            md_dir,
            converter,
            force=False,
            docling_only=False,
            chunk_size=8,
            sourcebook="Mistborn",
            vault_dir=vault_dir,
        )

        assert final_md == md_dir / "04-Paths - DOCLING.md"
        mock_convert.assert_called_once()
        mock_extract_async.assert_called_once()
        mock_shred.assert_called_once()
        mock_patch.assert_called_once_with(final_md)


def test_process_chapter_docling_only_flag(tmp_path: Path):
    pdf = tmp_path / "04-Paths.pdf"
    pdf.write_text("dummy", encoding="utf-8")
    md_dir = tmp_path / "md"
    md_dir.mkdir()

    chap = Chapter(path=pdf, title="Heroic Paths", mechanics=True)
    converter = MagicMock()

    with (
        patch("ttrpg_markdown_pipeline.orchestrator.convert_pdf") as mock_convert,
        patch("ttrpg_markdown_pipeline.orchestrator.extract_pdf_async") as mock_extract_async,
        patch("ttrpg_markdown_pipeline.orchestrator.shred_chapter") as mock_shred,
        patch("ttrpg_markdown_pipeline.orchestrator.patch_file") as mock_patch,
    ):
        mock_convert.side_effect = lambda src, dst, **kwargs: dst.write_text("docling", encoding="utf-8") or dst

        final_md = process_chapter(chap, md_dir, converter, force=False, docling_only=True, chunk_size=8)

        assert final_md == md_dir / "04-Paths - DOCLING.md"
        mock_convert.assert_called_once()
        mock_extract_async.assert_not_called()
        mock_shred.assert_not_called()
        mock_patch.assert_called_once_with(final_md)


def test_split_pdf_by_chapters_all_mechanics(sample_pdf_with_toc: Path, tmp_path: Path):
    split_dir = tmp_path / "PDF_Chapters"
    chapters = split_pdf_by_chapters(sample_pdf_with_toc, split_dir, all_mechanics=True)

    assert len(chapters) == 3
    # With all_mechanics=True, even Introduction should have mechanics=True
    assert chapters[0].mechanics is True
    assert chapters[1].mechanics is True
    assert chapters[2].mechanics is True
