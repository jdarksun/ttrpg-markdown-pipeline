"""Tests for OKF Shredder."""

import json
from pathlib import Path

import yaml

from ttrpg_markdown_pipeline.processors.shredder import (
    clean_extraction_artifacts,
    consolidate_concepts,
    instantiate_okf_concept,
    parse_gemini_json_payload,
    sanitize_slug,
    shred_chapter,
    split_docling_by_headers,
    split_mechanics_and_examples,
)


def test_sanitize_slug():
    assert sanitize_slug("Steel Bubble") == "steel_bubble"
    assert sanitize_slug("Pewterarm Weaponcraft (Era 2)") == "pewterarm_weaponcraft_era_2"
    assert sanitize_slug("Dueling Cane: Noble's Guard") == "dueling_cane_nobles_guard"


def test_split_docling_by_headers():
    docling_md = (
        "## Steel Bubble\n\n"
        "You create an invisible bubble around yourself.\n\n"
        "### Iron Stance\n\n"
        "You anchor yourself to metal in the ground.\n"
    )

    sections = split_docling_by_headers(docling_md)
    assert "steel_bubble" in sections
    assert "iron_stance" in sections
    assert "You create an invisible bubble around yourself." in sections["steel_bubble"]
    assert "You anchor yourself to metal in the ground." in sections["iron_stance"]


def test_parse_gemini_json_payload_fenced():
    raw_response = (
        "Here are the extracted concepts:\n\n"
        "```json\n"
        "[\n"
        '  {"name": "Steel Bubble", "type": "talent", "sourcebook": "Mistborn", '
        '"category": "Steel", "activation": "2 actions"}\n'
        "]\n"
        "```\n"
        "Enjoy!"
    )
    items = parse_gemini_json_payload(raw_response)
    assert len(items) == 1
    assert items[0]["name"] == "Steel Bubble"
    assert items[0]["activation"] == "2 actions"


def test_shred_chapter(tmp_path: Path):
    docling_file = tmp_path / "04-Chapter - DOCLING.md"
    docling_file.write_text(
        "## Steel Bubble\n\n"
        "You can enter another stance you know as ▷.\n\n"
        "## Dueling Cane\n\n"
        "A swift concealed weapon.\n",
        encoding="utf-8",
    )

    gemini_file = tmp_path / "04-Chapter - GEMINI.md"
    gemini_data = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "Mistborn World Guide",
            "type": "talent",
            "name": "Steel Bubble",
            "category": "Steel Allomancy",
            "prerequisites": "Steel 2+",
            "activation": "2 actions",
        },
        {
            "schema_version": "1.0.0",
            "sourcebook": "Mistborn World Guide",
            "type": "weapon",
            "name": "Dueling Cane",
            "category": "Light Weaponry",
            "damage": "1d6 physical",
            "traits": ["Discreet"],
        },
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_data)}\n```", encoding="utf-8")

    vault_dir = tmp_path / "okf_vault"
    saved = shred_chapter(docling_file, gemini_file, vault_dir)

    assert len(saved) == 2

    # Check talent file
    talent_file = vault_dir / "mistborn_world_guide" / "talents" / "steel_bubble.md"
    assert talent_file.exists()
    content = talent_file.read_text(encoding="utf-8")
    assert "activation: '[2 Actions]'" in content or 'activation: "[2 Actions]"' in content or "[2 Actions]" in content
    # Check that Docling text was repaired by inline fixes (▷ -> [Free Action])
    assert "[Free Action]" in content

    # Check weapon file
    weapon_file = vault_dir / "mistborn_world_guide" / "weapons" / "dueling_cane.md"
    assert weapon_file.exists()
    w_content = weapon_file.read_text(encoding="utf-8")
    parts = w_content.split("---\n")
    data = yaml.safe_load(parts[1])
    assert data["type"] == "weapon"
    assert data["damage"] == "1d6 physical"


def test_clean_extraction_artifacts():
    sample = (
        "Salt &amp; Pepper &lt;Special&gt;\n\n"
        "<!-- image -->\n\n"
        "Downloaded by Jane Doe on 1/1/2026 . Unauthorized distribution prohibited.\n\n"
        "●\n\n"
        "48\n\n"
        "M\n\n"
        "V\n\n"
        "<!--image-->\n\n"
        "• 52\n\n"
        "Actual rules content remains intact."
    )
    cleaned = clean_extraction_artifacts(sample)

    assert "Salt & Pepper <Special>" in cleaned
    assert "<!-- image -->" not in cleaned
    assert "<!--image-->" not in cleaned
    assert "Downloaded by" not in cleaned
    assert "Unauthorized distribution" not in cleaned
    assert "●" not in cleaned
    assert "•" not in cleaned
    assert "48" not in cleaned
    assert "52" not in cleaned
    assert "\nM\n" not in cleaned
    assert "\n\nV\n\n" not in cleaned
    assert "Actual rules content remains intact." in cleaned
    assert "\n\n\n" not in cleaned


def test_split_mechanics_and_examples_speaker_dialogue():
    text = (
        "When taking the Attack action, roll 1d20 plus your attack modifier.\n\n"
        "Joe: That's a Near Miss…\n\n"
        "Paige: Can one of you help out?\n\n"
        "Ben: I can."
    )
    mech, example = split_mechanics_and_examples(text)
    assert mech == "When taking the Attack action, roll 1d20 plus your attack modifier."
    assert example is not None
    assert "Joe: That's a Near Miss…" in example
    assert "Paige: Can one of you help out?" in example
    assert "Ben: I can." in example


def test_split_mechanics_and_examples_heading_block():
    text = (
        "You can spend 1 focus to reroll a failed test.\n\n"
        "### Example Play\n\n"
        "Koda wants to reroll a failed Stealth test.\n\n"
        "He spends 1 focus and succeeds."
    )
    mech, example = split_mechanics_and_examples(text)
    assert mech == "You can spend 1 focus to reroll a failed test."
    assert example is not None
    assert "### Example Play" in example
    assert "Koda wants to reroll" in example


def test_split_mechanics_and_examples_no_example():
    text = "This rule has only pure mechanics without any play examples."
    mech, example = split_mechanics_and_examples(text)
    assert mech == text
    assert example is None


def test_consolidate_concepts():
    chunk_data = [
        {
            "name": "Attack",
            "type": "rule",
            "sourcebook": "DCC RPG",
            "category": "Combat",
            "action_cost": "1 Action",
            "trigger": None,
            "body_text": "Brief table summary: Make an attack.",
        },
        {
            "name": "Attack",
            "type": "rule",
            "sourcebook": "DCC RPG Starter Set",
            "category": "Combat Actions",
            "action_cost": None,
            "trigger": "When in melee or ranged range",
            "body_text": "When you take an Attack action, roll 1d20 + modifier against Armor Class.",
            "example_text": "Joe: I attack the goblin!\nGM: Roll to hit.",
        },
        {
            "name": "Longsword",
            "type": "weapon",
            "traits": ["Versatile"],
            "damage": "1d8 physical",
        },
        {
            "name": "Longsword",
            "type": "weapon",
            "traits": ["Slashing", "Versatile"],
            "cost": "15 gp",
        },
    ]

    consolidated = consolidate_concepts(chunk_data)
    assert len(consolidated) == 2

    # Check Attack consolidation
    attack = consolidated[0]
    assert attack["name"] == "Attack"
    assert attack["action_cost"] == "1 Action"
    assert attack["trigger"] == "When in melee or ranged range"
    assert attack["body_text"] == "When you take an Attack action, roll 1d20 + modifier against Armor Class."
    assert "Joe: I attack the goblin!" in attack["example_text"]

    # Check Longsword consolidation
    sword = consolidated[1]
    assert sword["name"] == "Longsword"
    assert sword["damage"] == "1d8 physical"
    assert sword["cost"] == "15 gp"
    assert set(sword["traits"]) == {"Versatile", "Slashing"}


def test_shred_chapter_sourcebook_override_and_dedup(tmp_path: Path):
    docling_file = tmp_path / "05-Chapter - DOCLING.md"
    docling_file.write_text(
        "## Attack\n\nWhen you attack, roll 1d20.\n\n## Move\n\nYou move your speed.\n",
        encoding="utf-8",
    )

    gemini_file = tmp_path / "05-Chapter - GEMINI.md"
    gemini_data = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "DCC Random Hallucination",
            "type": "rule",
            "name": "Attack",
            "action_cost": "1 Action",
            "body_text": "When you attack, roll 1d20.",
        },
        {
            "schema_version": "1.0.0",
            "sourcebook": "DCC Another Variant",
            "type": "rule",
            "name": "Attack",
            "action_cost": "1 Action",
            "body_text": "When you attack, roll 1d20 against the target.",
        },
        {
            "schema_version": "1.0.0",
            "sourcebook": "DCC Starter Set",
            "type": "rule",
            "name": "Move",
            "action_cost": "1 Action",
            "body_text": "You move your speed.",
        },
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_data)}\n```", encoding="utf-8")

    vault_dir = tmp_path / "okf_vault"
    canonical_sourcebook = "Dungeon Crawler Carl Roleplaying Game"
    saved = shred_chapter(docling_file, gemini_file, vault_dir, default_sourcebook=canonical_sourcebook)

    assert len(saved) == 2

    # Check that both files are saved under the canonical sourcebook directory
    source_slug = sanitize_slug(canonical_sourcebook)
    attack_file = vault_dir / source_slug / "rules" / "attack.md"
    move_file = vault_dir / source_slug / "rules" / "move.md"

    assert attack_file.exists()
    assert move_file.exists()

    # Verify that hallucinated sourcebook folder was NOT created
    assert not (vault_dir / "dcc_random_hallucination").exists()
    assert not (vault_dir / "dcc_starter_set").exists()

    # Verify content of attack was consolidated
    content = yaml.safe_load(attack_file.read_text(encoding="utf-8").split("---\n")[1])
    assert content["sourcebook"] == canonical_sourcebook


def test_shred_adventure_node_and_lore(tmp_path: Path):
    docling_file = tmp_path / "01-Part_1 - DOCLING.md"
    docling_file.write_text("## Alethi Ambush\n\nArrows rain down on the caravan.", encoding="utf-8")

    gemini_file = tmp_path / "01-Part_1 - GEMINI.md"
    gemini_data = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "Stormlight Solo",
            "type": "adventure_node",
            "node_id": "A1",
            "name": "Alethi Ambush",
            "category": "Part 1",
            "read_aloud": "Arrows rain down from the ridge.",
            "body_text": "Parshendi attack the wagons.",
            "skill_checks": [{"skill": "Athletics", "dc": 14, "success": "Take cover"}],
            "choices": [{"option": "Charge", "target_node": "A2"}],
        },
        {
            "schema_version": "1.0.0",
            "sourcebook": "Stormlight Solo",
            "type": "faction",
            "name": "Ghostbloods",
            "category": "Factions",
            "key_themes": ["Intrigue"],
            "adventure_hooks": ["Find the spy."],
            "body_text": "A covert organization.",
        },
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_data)}\n```", encoding="utf-8")

    vault_dir = tmp_path / "okf_vault"
    saved = shred_chapter(docling_file, gemini_file, vault_dir, default_sourcebook="Stormlight Solo")

    assert len(saved) == 2
    node_file = vault_dir / "stormlight_solo" / "adventure_nodes" / "a1_alethi_ambush.md"
    faction_file = vault_dir / "stormlight_solo" / "factions" / "ghostbloods.md"

    assert node_file.exists()
    assert faction_file.exists()

    node_text = node_file.read_text(encoding="utf-8")
    assert "node_id: A1" in node_text
    assert "### Read-Aloud" in node_text
    assert "### Skill Checks" in node_text
    assert "### Choices & Branches" in node_text


def test_consolidate_adventure_nodes_and_lore():
    chunk1 = [
        {
            "type": "adventure_node",
            "node_id": "A1",
            "name": "The Ambush",
            "category": "Part 1",
            "state_mutations": ["Resources -1"],
            "choices": [{"option": "Fight", "target_node": "A2"}],
            "body_text": "Short intro.",
        },
        {
            "type": "lore",
            "name": "Roshar",
            "category": "Cosmology",
            "key_themes": ["Highstorms"],
            "adventure_hooks": ["Survive the storm."],
            "body_text": "A world of stone.",
        },
    ]
    chunk2 = [
        {
            "type": "adventure_node",
            "node_id": "A1",
            "name": "The Ambush Detailed",
            "category": "Part 1",
            "state_mutations": ["Attribute +1 Speed"],
            "choices": [{"option": "Flee", "target_node": "A3"}],
            "body_text": "A much longer and richer description of the ambush scene.",
        },
        {
            "type": "lore",
            "name": "Roshar",
            "category": "Cosmology",
            "key_themes": ["Spren"],
            "adventure_hooks": ["Bond a spren."],
            "body_text": "A world of stone and storm.",
        },
    ]

    merged = consolidate_concepts(chunk1 + chunk2)
    assert len(merged) == 2

    merged_node = next(c for c in merged if c["type"] == "adventure_node")
    assert "Resources -1" in merged_node["state_mutations"]
    assert "Attribute +1 Speed" in merged_node["state_mutations"]
    assert len(merged_node["choices"]) == 2
    assert "much longer and richer" in merged_node["body_text"]

    merged_lore = next(c for c in merged if c["type"] == "lore")
    assert "Highstorms" in merged_lore["key_themes"]
    assert "Spren" in merged_lore["key_themes"]
    assert len(merged_lore["adventure_hooks"]) == 2


def test_split_mechanics_and_examples_preserves_stat_block_labels():
    companion_stat_block = (
        "Synthetic Companion - Small Construct\n\n"
        "Deflect: 2 (plating)\n\n"
        "Movement: 30 ft., climb 20 ft.\n\n"
        "Senses: 20 ft. (darkvision)\n\n"
        "Physical Skills: Agility +4\n\n"
        "Spiritual Skills: Insight +3, Perception +4\n\n"
        "Languages: understands trade tongue, but cannot speak"
    )
    mech, example = split_mechanics_and_examples(companion_stat_block)
    assert example is None
    assert "Deflect: 2 (plating)" in mech
    assert "Movement: 30 ft., climb 20 ft." in mech
    assert "Physical Skills: Agility +4" in mech
    assert "Languages: understands trade tongue" in mech


def test_instantiate_okf_concept_prefers_gemini_body_over_docling():
    item = {
        "name": "Stone Shaping",
        "type": "rule",
        "sourcebook": "Sample Rulebook",
        "action_cost": "1 Action",
        "body_text": "Use [1 Action] to mold stone into a simple tool.",
    }
    noisy_docling = "Use  to mold stone into a simple tool.\n\nILLUSTRATOR CREDIT\n\nChapter 6: Powers"
    concept = instantiate_okf_concept(item, docling_body=noisy_docling)
    assert "Use [1 Action] to mold stone" in concept.body_text
    assert "ILLUSTRATOR CREDIT" not in concept.body_text
    assert "Chapter 6: Powers" not in concept.body_text
