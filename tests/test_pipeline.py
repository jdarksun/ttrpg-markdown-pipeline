from pathlib import Path

import pymupdf
import pytest

from ttrpg_markdown_pipeline.common import (
    DOCLING_TAG,
    GEMINI_TAG,
    clean_path,
    resolve_md_output,
    strip_tags,
    tagged_md_path,
)
from ttrpg_markdown_pipeline.orchestrator import sanitize_filename, split_pdf_by_chapters
from ttrpg_markdown_pipeline.processors.merge import extract_talent_metadata, merge_chapter
from ttrpg_markdown_pipeline.processors.patch import find_final_outputs, patch_file
from ttrpg_markdown_pipeline.rules.cosmere import (
    MECHANICS_KEYWORDS,
    patch_cosmere_rules,
)


# ==============================================================================
# 1. Path & Filename Helpers
# ==============================================================================
def test_clean_path():
    assert clean_path(r'"C:\path\to\file.pdf"') == Path(r"C:\path\to\file.pdf")
    assert clean_path("  'some/path/file.pdf'  ") == Path("some/path/file.pdf")


def test_tagged_md_path(tmp_path: Path):
    d = tmp_path / "out"
    # Basic tagging
    assert tagged_md_path(d, "04-Heroic_Paths", DOCLING_TAG) == d / "04-Heroic_Paths - DOCLING.md"
    # Prevents duplicate tag
    assert tagged_md_path(d, "04-Heroic_Paths - DOCLING", DOCLING_TAG) == d / "04-Heroic_Paths - DOCLING.md"
    # Correctly swaps existing tag
    assert tagged_md_path(d, "04-Heroic_Paths - DOCLING", GEMINI_TAG) == d / "04-Heroic_Paths - GEMINI.md"
    assert tagged_md_path(d, "04-Heroic_Paths - MERGED", DOCLING_TAG) == d / "04-Heroic_Paths - DOCLING.md"


def test_strip_tags():
    assert strip_tags("04-Heroic_Paths - DOCLING") == "04-Heroic_Paths"
    assert strip_tags("04-Heroic_Paths - GEMINI") == "04-Heroic_Paths"
    assert strip_tags("04-Heroic_Paths - MERGED") == "04-Heroic_Paths"
    assert strip_tags("04-Heroic_Paths") == "04-Heroic_Paths"


def test_resolve_md_output(tmp_path: Path):
    d = tmp_path / "default_dir"
    stem = "04-Heroic_Paths"

    # None -> default_dir / <stem><tag>.md
    res = resolve_md_output(None, d, stem, DOCLING_TAG)
    assert res == d / f"{stem}{DOCLING_TAG}.md"

    # Directory provided -> dir / <stem><tag>.md
    custom_dir = tmp_path / "custom_dir"
    res = resolve_md_output(custom_dir, d, stem, DOCLING_TAG)
    assert res == custom_dir / f"{stem}{DOCLING_TAG}.md"

    # Explicit .md file path provided -> file with tag injected
    file_path = tmp_path / "custom_file.md"
    res = resolve_md_output(file_path, d, stem, GEMINI_TAG)
    assert res == tmp_path / f"custom_file{GEMINI_TAG}.md"


def test_sanitize_filename():
    assert sanitize_filename('Chapter: "Combat" & Actions?') == "Chapter Combat & Actions"
    assert sanitize_filename("Path/To/File|Name*") == "PathToFileName"


# ==============================================================================
# 2. Talent Metadata Extraction (Gemini Output Parsing)
# ==============================================================================
def test_extract_talent_metadata():
    gemini_sample = """
    ### Iron Stance
    - **Prerequisites:** Strength 14
    - **Activation:** [1 Action]

    ### Steel Bubble (Specialty)
    **Prerequisite:** Iron Stance
    **Activation:** Special Activation

    ## Passive Recovery
    - **Prerequisites:** None
    - **Activation:** Passive

    #### Rapid Strike
    **Prerequisites:** Agility 12
    **Activation:** [Reaction]
    """
    metadata = extract_talent_metadata(gemini_sample)

    assert "iron stance" in metadata
    assert metadata["iron stance"]["raw_name"] == "Iron Stance"
    assert metadata["iron stance"]["prereq"] == "Strength 14"
    assert metadata["iron stance"]["act"] == "[1 Action]"

    # Subtitle in parentheses is stripped
    assert "steel bubble" in metadata
    assert metadata["steel bubble"]["raw_name"] == "Steel Bubble"
    assert metadata["steel bubble"]["act"] == "[Special Activation]"

    # 'Passive' mapped to '[Passive]'
    assert "passive recovery" in metadata
    assert metadata["passive recovery"]["act"] == "[Passive]"

    # Lower header levels and reaction activation
    assert "rapid strike" in metadata
    assert metadata["rapid strike"]["act"] == "[Reaction]"


# ==============================================================================
# 3. Merge Engine (Docling Layout + Gemini Metadata)
# ==============================================================================
def test_merge_chapter(tmp_path: Path):
    docling_file = tmp_path / "04-Chapter - DOCLING.md"
    gemini_file = tmp_path / "04-Chapter - GEMINI.md"
    out_file = tmp_path / "04-Chapter - MERGED.md"

    # Docling output with:
    # 1. A compressed talent header (Prerequisite and Activation on adjacent lines)
    # 2. A talent that lost its Activation line entirely
    # 3. An inline glyph gap
    docling_text = """
# Heroic Paths

## Steady Aim
Prerequisite: None
Activation:
You take steady aim at a distant foe.
Recover action as .

## Iron Will
You steel your mind against cognitive tests.
gain for cognitive tests.
"""

    gemini_text = """
### Steady Aim
- **Prerequisites:** None
- **Activation:** [2 Actions]

### Iron Will
- **Prerequisites:** Resolve 12
- **Activation:** [Passive]
"""

    docling_file.write_text(docling_text, encoding="utf-8")
    gemini_file.write_text(gemini_text, encoding="utf-8")

    merge_chapter(docling_file, gemini_file, out_file)

    merged_text = out_file.read_text(encoding="utf-8")

    # Primary pass verification:
    assert "### Steady Aim" in merged_text
    assert "- **Prerequisites:** None" in merged_text
    assert "- **Activation:** [2 Actions]" in merged_text

    # Fallback pass verification:
    assert "### Iron Will" in merged_text
    assert "- **Prerequisites:** Resolve 12" in merged_text
    assert "- **Activation:** [Passive]" in merged_text

    # Universal inline fix verification:
    assert "gain [2 Actions] for cognitive tests." in merged_text


# ==============================================================================
# 4. Glyph & Text Patching Rules
# ==============================================================================
def test_patch_cosmere_rules():
    sample = (
        "Actions (). Reactions (). Free Actions ().\n"
        "Opportunity symbol () and Complication symbol ().\n"
        "As , you can move.\n"
        "action as . Before you take damage\n"
        "Recover action as .\n"
        "## Flowchart Step 8\n"
        "Activation:\n"
    )

    patched = patch_cosmere_rules(sample)

    assert "Actions ([1 / 2 / 3 Actions])." in patched
    assert "Reactions ([Reaction])." in patched
    assert "Free Actions ([Free Action])." in patched
    assert "Opportunity symbol ([Opportunity])" in patched
    assert "Complication symbol ([Complication])" in patched
    assert "As [1 Action], you can move." in patched
    assert "action as [Reaction]. Before you take damage" in patched
    assert "Recover action as [1 Action]." in patched
    assert "## Flowchart Step" in patched
    assert "Activation: [Passive / Varies]" in patched


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


# ==============================================================================
# 5. TOC Splitting & Page Boundary Math
# ==============================================================================
def test_split_pdf_by_chapters(tmp_path: Path):
    # Create synthetic 10-page master PDF with TOC
    pdf_path = tmp_path / "Master_Rulebook.pdf"
    doc = pymupdf.open()
    for i in range(10):
        doc.new_page().insert_text((72, 72), f"Physical Page {i + 1}")

    # TOC entries: [level, title, page_number (1-indexed)]
    toc = [
        [1, "Introduction", 1],  # Pages 1 to 2
        [1, "Chapter 4: Heroic Paths", 3],  # Pages 3 to 6
        [1, "Chapter 8: Combat Rules", 7],  # Pages 7 to 10
    ]
    doc.set_toc(toc)
    doc.save(pdf_path)
    doc.close()

    split_dir = tmp_path / "PDF_Chapters"
    chapters = split_pdf_by_chapters(pdf_path, split_dir)

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


def test_split_pdf_no_toc_raises_error(tmp_path: Path):
    bare_pdf = tmp_path / "Bare.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(bare_pdf)
    doc.close()

    with pytest.raises(ValueError, match="No Table of Contents found"):
        split_pdf_by_chapters(bare_pdf, tmp_path / "split")


def test_mechanics_keyword_matching():
    assert any(kw in "04-Heroic_Paths".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Combat & Action Economy".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Metallic Arts".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Adversaries".lower() for kw in MECHANICS_KEYWORDS)
    assert not any(kw in "World of Scadrial Overview".lower() for kw in MECHANICS_KEYWORDS)
