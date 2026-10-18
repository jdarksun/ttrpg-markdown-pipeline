from pathlib import Path

from ttrpg_markdown_pipeline.common import (
    DOCLING_TAG,
    GEMINI_TAG,
    clean_path,
    resolve_md_output,
    strip_tags,
    tagged_md_path,
)


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


def test_load_env_file(tmp_path: Path, monkeypatch):
    import os

    from ttrpg_markdown_pipeline.common import load_env_file

    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test_secret_key_123\n# A comment\nOTHER_VAR='hello'", encoding="utf-8")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    load_env_file()
    assert os.environ.get("GEMINI_API_KEY") == "test_secret_key_123"
    assert os.environ.get("OTHER_VAR") == "hello"
