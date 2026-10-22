"""Tests for NotebookLM Bundler."""

from pathlib import Path

from ttrpg_markdown_pipeline.processors.bundler import (
    bundle_campaign,
    bundle_category,
    bundle_vault,
    format_concept_for_bundle,
    natural_sort_key,
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


def test_natural_sort_key():
    files = [
        Path("a10_climax.md"),
        Path("a1_intro.md"),
        Path("a2_crossroads.md"),
        Path("b1_part2.md"),
    ]
    sorted_files = sorted(files, key=natural_sort_key)
    expected = [
        Path("a1_intro.md"),
        Path("a2_crossroads.md"),
        Path("a10_climax.md"),
        Path("b1_part2.md"),
    ]
    assert sorted_files == expected


def test_bundle_campaign(tmp_path: Path):
    vault = tmp_path / "okf_vault"
    adv_dir = vault / "stormlight_solo" / "adventure_nodes"
    adv_dir.mkdir(parents=True, exist_ok=True)

    adv1 = adv_dir / "a1_intro.md"
    adv1.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "type: adventure_node\n"
        "name: Ambush Opening\n"
        "node_id: A1\n"
        "---\n\n"
        "### Read-Aloud\n\n"
        "> Arrows rain down.\n\n"
        "### Scene & Mechanics\n\n"
        "Parshendi attack.",
        encoding="utf-8",
    )

    adv2 = adv_dir / "a2_charge.md"
    adv2.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "type: adventure_node\n"
        "name: Counter Attack\n"
        "node_id: A2\n"
        "---\n\n"
        "### Scene & Mechanics\n\n"
        "You counter-charge the archers.",
        encoding="utf-8",
    )

    # Sibling adversary directory
    adv_monsters = vault / "stormlight_solo" / "adversaries"
    adv_monsters.mkdir(parents=True, exist_ok=True)
    axehound = adv_monsters / "axehound.md"
    axehound.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "type: adversary\n"
        "name: Axehound\n"
        "tier: 1\n"
        "---\n\n"
        "### Mechanics\n\n"
        "Fierce crustacean-canine beast.",
        encoding="utf-8",
    )

    out_dir = tmp_path / "bundles"
    campaign_files = bundle_campaign(vault, out_dir)

    assert len(campaign_files) == 1
    guide = campaign_files[0]
    assert guide.name == "Stormlight_Solo_GM_Campaign_Guide.md"

    text = guide.read_text(encoding="utf-8")
    assert "# Stormlight Solo - Interactive GM Campaign Guide" in text
    assert "> ## GM / Solo Referee System Instructions" in text
    assert "### Operational Protocol:" in text
    assert "## Ambush Opening" in text
    assert "## Counter Attack" in text
    assert "# Module Compendium: Adversaries" in text
    assert "## Axehound" in text
    assert "Fierce crustacean-canine beast." in text


def test_bundle_vault_includes_campaign(tmp_path: Path):
    vault = tmp_path / "okf_vault"
    adv_dir = vault / "stormlight_solo" / "adventure_nodes"
    adv_dir.mkdir(parents=True, exist_ok=True)
    (adv_dir / "a1.md").write_text(
        "---\ntype: adventure_node\nname: Scene 1\nnode_id: A1\n---\n\nScene 1 text.",
        encoding="utf-8",
    )

    out_dir = tmp_path / "bundles"
    bundles = bundle_vault(vault, out_dir)
    names = {b.name for b in bundles}

    assert "Stormlight_Solo_All_Adventure_Nodes.md" in names
    assert "Stormlight_Solo_GM_Campaign_Guide.md" in names
