"""Tests for NotebookLM Bundler."""

from pathlib import Path

from ttrpg_markdown_pipeline.processors.bundler import (
    bundle_category,
    bundle_vault,
    sanitize_bundle_name,
)


def test_sanitize_bundle_name():
    assert sanitize_bundle_name("mistborn", "talents") == "Mistborn_All_Talents.md"
    assert sanitize_bundle_name("stormlight_rpg", "weapons") == "Stormlight_Rpg_All_Weapons.md"


def test_bundle_category(tmp_path: Path):
    vault = tmp_path / "okf_vault"
    talents_dir = vault / "mistborn" / "talents"
    talents_dir.mkdir(parents=True, exist_ok=True)

    t1 = talents_dir / "steel_bubble.md"
    t1.write_text("---\nname: Steel Bubble\ntype: talent\n---\n\nCreates bubble.", encoding="utf-8")

    t2 = talents_dir / "iron_stance.md"
    t2.write_text("---\nname: Iron Stance\ntype: talent\n---\n\nAnchors feet.", encoding="utf-8")

    out_dir = tmp_path / "bundles"
    bundle_file = bundle_category(vault, "mistborn", "talents", out_dir)

    assert bundle_file is not None
    assert bundle_file.name == "Mistborn_All_Talents.md"
    content = bundle_file.read_text(encoding="utf-8")
    assert "name: Steel Bubble" in content
    assert "name: Iron Stance" in content
    assert "Creates bubble." in content
    assert "Anchors feet." in content


def test_bundle_vault(tmp_path: Path):
    vault = tmp_path / "okf_vault"
    (vault / "mistborn" / "talents").mkdir(parents=True, exist_ok=True)
    (vault / "mistborn" / "weapons").mkdir(parents=True, exist_ok=True)

    (vault / "mistborn" / "talents" / "pewter_punch.md").write_text(
        "---\nname: Pewter Punch\ntype: talent\n---\n\nPunches hard.",
        encoding="utf-8",
    )
    (vault / "mistborn" / "weapons" / "dueling_cane.md").write_text(
        "---\nname: Dueling Cane\ntype: weapon\n---\n\nCane weapon.",
        encoding="utf-8",
    )

    out_dir = tmp_path / "bundles"
    bundles = bundle_vault(vault, out_dir)

    assert len(bundles) == 2
    bundle_names = {b.name for b in bundles}
    assert "Mistborn_All_Talents.md" in bundle_names
    assert "Mistborn_All_Weapons.md" in bundle_names
