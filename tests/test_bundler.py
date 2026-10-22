"""Tests for NotebookLM Bundler."""

from pathlib import Path

from ttrpg_markdown_pipeline.processors.bundler import (
    bundle_category,
    bundle_vault,
    format_concept_for_bundle,
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
    assert "## Steel Bubble" in content
    assert "## Iron Stance" in content
    assert "```yaml" in content
    assert "name: Steel Bubble" in content
    assert "name: Iron Stance" in content
    assert "Creates bubble." in content
    assert "Anchors feet." in content


def test_format_concept_for_bundle():
    atomic_md = (
        "---\n"
        "schema_version: 1.0.0\n"
        "type: rule\n"
        "name: Attack\n"
        "category: Combat\n"
        "action_cost: '[1 Action]'\n"
        "---\n\n"
        "### Mechanics\n\n"
        "When taking an attack, roll 1d20.\n\n"
        "### Example Play\n\n"
        "Joe: I swing my sword!"
    )
    formatted = format_concept_for_bundle(atomic_md)
    assert formatted.startswith("## Attack\n\n```yaml\n")
    assert "name: Attack" in formatted
    assert "action_cost: '[1 Action]'" in formatted
    assert "```\n\n### Mechanics" in formatted
    assert "When taking an attack, roll 1d20." in formatted
    assert "### Example Play" in formatted
    assert "Joe: I swing my sword!" in formatted


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


def test_bundle_end_to_end_format_and_cleanliness(tmp_path: Path):
    vault = tmp_path / "okf_vault"
    rules_dir = vault / "dungeon_crawler_carl" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    r1 = rules_dir / "attack.md"
    r1.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "type: rule\n"
        "sourcebook: Dungeon Crawler Carl\n"
        "name: Attack\n"
        "category: Combat Actions\n"
        "action_cost: '[1 Action]'\n"
        "trigger: null\n"
        "---\n\n"
        "### Mechanics\n\n"
        "Roll 1d20 to attack.\n\n"
        "### Example Play\n\n"
        "Joe: I hit the goblin!\n\n"
        "Paige: Great hit.",
        encoding="utf-8",
    )

    r2 = rules_dir / "intervene.md"
    r2.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "type: rule\n"
        "sourcebook: Dungeon Crawler Carl\n"
        "name: Intervene\n"
        "category: Reactions\n"
        "action_cost: '[Reaction]'\n"
        "trigger: When an ally is attacked\n"
        "---\n\n"
        "### Mechanics\n\n"
        "Step in front of an attack.\n\n"
        "### Example Play\n\n"
        "Andrew: I step in front of Kai.",
        encoding="utf-8",
    )

    out_dir = tmp_path / "bundles"
    bundle_file = bundle_category(vault, "dungeon_crawler_carl", "rules", out_dir)
    assert bundle_file is not None

    bundle_text = bundle_file.read_text(encoding="utf-8")

    # Assert standard ATX headings
    assert "## Attack" in bundle_text
    assert "## Intervene" in bundle_text

    # Assert fenced YAML code blocks
    assert "```yaml\nschema_version: 1.0.0\ntype: rule\nsourcebook: Dungeon Crawler Carl\nname: Attack" in bundle_text
    assert (
        "```yaml\nschema_version: 1.0.0\ntype: rule\nsourcebook: Dungeon Crawler Carl\nname: Intervene" in bundle_text
    )

    # Assert Mechanics and Example Play sections
    assert "### Mechanics\n\nRoll 1d20 to attack." in bundle_text
    assert "### Example Play\n\nJoe: I hit the goblin!" in bundle_text
    assert "### Mechanics\n\nStep in front of an attack." in bundle_text
    assert "### Example Play\n\nAndrew: I step in front of Kai." in bundle_text

    # Ensure no Setext collisions (no mid-document '---' directly followed by 'schema_version')
    assert "---\nschema_version" not in bundle_text
    assert "#### schema_version" not in bundle_text
