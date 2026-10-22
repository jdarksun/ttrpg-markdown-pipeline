from pathlib import Path

from ttrpg_markdown_pipeline.processors.patch import find_final_outputs, patch_file


def test_patch_file(tmp_path: Path):
    target = tmp_path / "test.md"
    target.write_text("As , you can jump.", encoding="utf-8")

    changed = patch_file(target)
    assert changed is True
    assert "As [1 Action], you can jump." in target.read_text(encoding="utf-8")

    # Re-running on already-patched file returns False (idempotent)
    assert patch_file(target) is False


def test_find_final_outputs(tmp_path: Path):
    # Setup directory with mixed stages:
    # 1. 01-Intro narrative (only DOCLING)
    (tmp_path / "01-Intro - DOCLING.md").write_text("", encoding="utf-8")
    # 2. 04-Paths mechanics (DOCLING, GEMINI, and final MERGED)
    (tmp_path / "04-Paths - DOCLING.md").write_text("", encoding="utf-8")
    (tmp_path / "04-Paths - GEMINI.md").write_text("", encoding="utf-8")
    (tmp_path / "04-Paths - MERGED.md").write_text("", encoding="utf-8")

    final_outputs = find_final_outputs(tmp_path)
    final_names = [f.name for f in final_outputs]

    # Should include 01-Intro (DOCLING is final) and 04-Paths (MERGED is final)
    assert "01-Intro - DOCLING.md" in final_names
    assert "04-Paths - MERGED.md" in final_names
    # Should safely exclude intermediate files
    assert "04-Paths - DOCLING.md" not in final_names
    assert "04-Paths - GEMINI.md" not in final_names
