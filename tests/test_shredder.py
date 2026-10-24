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


def test_parse_gemini_json_payload_handles_truncated_chunk_without_poisoning_next_chunk():
    raw_multi_chunk = (
        '```json\n[\n  {"name": "Step 1: Origins", "type": "rule"},\n'
        '  {"name": "Step 3: Attributes", "body_text": "Truncated mid-string\n\n---\n\n'
        '```json\n[\n  {"name": "Step 4: Skills", "type": "rule"}\n]\n```'
    )
    items = parse_gemini_json_payload(raw_multi_chunk)
    names = [item["name"] for item in items]
    assert "Step 1: Origins" in names
    assert "Step 4: Skills" in names


def test_consolidate_concepts_subsumption():
    parent_rule = {
        "name": "Opportunities and Complications",
        "type": "rule",
        "category": "Resolution",
        "body_text": (
            "Opportunities and complications add dynamic flair to tests.\n\n"
            "### Spending an Opportunity\n"
            "When you roll an opportunity on the plot die, you may spend it to activate a special effect "
            "or grant an advantage to an ally.\n\n"
            "### Facing a Complication\n"
            "When you roll a complication, the GM may introduce an unexpected setback or danger."
        ),
        "example_text": None,
    }
    child_rule = {
        "name": "Spending an Opportunity",
        "type": "rule",
        "category": "Resolution",
        "body_text": (
            "When you roll an opportunity on the plot die, you may spend it to activate a special effect "
            "or grant an advantage to an ally."
        ),
        "example_text": "GM: You rolled an opportunity!\nPlayer: I spend it to help Kelsier.",
    }
    standalone_rule = {
        "name": "Disengage",
        "type": "rule",
        "category": "Combat",
        "body_text": "Spend [1 Action] to move away safely.",
    }

    consolidated = consolidate_concepts([child_rule, parent_rule, standalone_rule])

    # child_rule should be subsumed into parent_rule; standalone_rule remains
    assert len(consolidated) == 2
    names = [item["name"] for item in consolidated]
    assert "Opportunities and Complications" in names
    assert "Disengage" in names
    assert "Spending an Opportunity" not in names

    # The parent rule should now hold the child's example_text
    parent_merged = next(item for item in consolidated if item["name"] == "Opportunities and Complications")
    assert parent_merged["example_text"] is not None
    assert "GM: You rolled an opportunity!" in parent_merged["example_text"]


def test_split_docling_by_headers_hierarchy():
    docling_md = (
        "## Core Subsystem\n\n"
        "Overview of the subsystem.\n\n"
        "### Step 1: Initialization\n\n"
        "First step details.\n\n"
        "### Step 2: Resolution\n\n"
        "Second step details.\n\n"
        "## Next Major System\n\n"
        "Overview of the next system.\n"
    )

    sections = split_docling_by_headers(docling_md)
    assert "core_subsystem" in sections
    assert "step_1_initialization" in sections
    assert "step_2_resolution" in sections
    assert "next_major_system" in sections

    # Parent section includes both sub-steps
    core_text = sections["core_subsystem"]
    assert "Overview of the subsystem." in core_text
    assert "### Step 1: Initialization" in core_text
    assert "First step details." in core_text
    assert "### Step 2: Resolution" in core_text
    assert "Second step details." in core_text
    # Does not include the next ## heading
    assert "Next Major System" not in core_text

    # Child sections are individually accessible
    assert "First step details." in sections["step_1_initialization"]
    assert "### Step 2: Resolution" not in sections["step_1_initialization"]


def test_shred_chapter_preserves_body_with_horizontal_rule(tmp_path: Path):
    vault_dir = tmp_path / "okf_vault"
    source_dir = vault_dir / "mistborn_world_guide" / "rules"
    source_dir.mkdir(parents=True, exist_ok=True)

    rule_file = source_dir / "complex_resolution.md"
    initial_content = (
        "---\n"
        "schema_version: 1.0.0\n"
        "sourcebook: Mistborn World Guide\n"
        "name: Complex Resolution\n"
        "type: rule\n"
        "---\n\n"
        "Section 1 before horizontal rule.\n\n"
        "---\n\n"
        "Section 2 after horizontal rule.\n"
    )
    rule_file.write_text(initial_content, encoding="utf-8")

    gemini_file = tmp_path / "01-Chapter - GEMINI.md"
    gemini_payload = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "Mistborn World Guide",
            "name": "Complex Resolution",
            "type": "rule",
            "body_text": "Section 1 before horizontal rule.\n\n---\n\nSection 2 after horizontal rule.",
        }
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_payload)}\n```", encoding="utf-8")

    shred_chapter(None, gemini_file, vault_dir, default_sourcebook="Mistborn World Guide")

    updated_content = rule_file.read_text(encoding="utf-8")
    assert "Section 1 before horizontal rule." in updated_content
    assert "Section 2 after horizontal rule." in updated_content


def test_shred_chapter_orphan_cleanup(tmp_path: Path):
    vault_dir = tmp_path / "okf_vault"
    source_dir = vault_dir / "stormlight_rpg" / "rules"
    source_dir.mkdir(parents=True, exist_ok=True)

    # Simulate an orphaned child file left from an earlier run
    orphan_file = source_dir / "spending_an_opportunity.md"
    orphan_file.write_text(
        "---\n"
        "schema_version: 1.0.0\n"
        "sourcebook: Stormlight RPG\n"
        "name: Spending an Opportunity\n"
        "type: rule\n"
        "---\n\n"
        "When you roll an opportunity, spend it to activate a talent.\n",
        encoding="utf-8",
    )
    assert orphan_file.exists()

    gemini_file = tmp_path / "02-Chapter - GEMINI.md"
    gemini_payload = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "Stormlight RPG",
            "name": "Opportunities and Complications",
            "type": "rule",
            "body_text": (
                "Opportunities and complications provide narrative turns.\n\n"
                "### Spending an Opportunity\n"
                "When you roll an opportunity, spend it to activate a talent.\n\n"
                "### Facing a Complication\n"
                "Complications introduce GM moves.\n"
            ),
        }
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_payload)}\n```", encoding="utf-8")

    saved = shred_chapter(None, gemini_file, vault_dir, default_sourcebook="Stormlight RPG")

    # Parent rule is saved
    parent_file = source_dir / "opportunities_and_complications.md"
    assert parent_file.exists()
    assert parent_file in saved

    # The orphaned child file was removed
    assert not orphan_file.exists()
    assert orphan_file not in saved


def test_consolidate_concepts_procedural_category_rollup():
    """Verifies that child rules matching a parent procedural rule's category roll into parent ### headings."""
    concepts = [
        {
            "name": "Step 5: Talents",
            "type": "rule",
            "category": "Character Creation",
            "body_text": "Select your heroic talents.",
        },
        {
            "name": "Gain Your Key Talent",
            "type": "rule",
            "category": "Step 5: Talents",
            "body_text": "You gain your path's key talent automatically.",
            "example_text": "GM: You gain Shardblade Master.",
        },
        {
            "name": "Choose an Ancestry Talent",
            "type": "rule",
            "category": "Step 5: Talents",
            "body_text": "Pick one talent from your ancestry list.",
        },
        {
            "name": "Strike",
            "type": "rule",
            "category": "Combat Actions",
            "action_cost": "[1 Action]",
            "body_text": "Make a weapon attack.",
        },
        {
            "name": "Ghostbloods",
            "type": "faction",
            "category": "Factions",
            "body_text": "A covert Cosmere organization.",  # < 100 chars and no hooks -> filtered
        },
    ]

    consolidated = consolidate_concepts(concepts)
    # The 2 child rules rolled into parent, ghostbloods stub filtered, strike retained
    assert len(consolidated) == 2

    step5 = next(c for c in consolidated if c["name"] == "Step 5: Talents")
    assert "### Gain Your Key Talent" in step5["body_text"]
    assert "You gain your path's key talent automatically." in step5["body_text"]
    assert "### Choose an Ancestry Talent" in step5["body_text"]
    assert "Pick one talent from your ancestry list." in step5["body_text"]
    assert "Shardblade Master" in step5["example_text"]

    strike = next(c for c in consolidated if c["name"] == "Strike")
    assert strike["action_cost"] == "[1 Action]"


def test_parse_vault_markdown_body_lore_and_adventure_idempotent():
    """Verifies that _parse_vault_markdown_body strips rendered headings & trailers for idempotent re-saving."""
    from ttrpg_markdown_pipeline.models import OKFAdventureNode, OKFLoreEntry
    from ttrpg_markdown_pipeline.processors.shredder import _parse_vault_markdown_body

    # 1. OKFLoreEntry idempotency
    lore = OKFLoreEntry(
        schema_version="1.0.0",
        sourcebook="Roshar Guide",
        name="Urithiru",
        category="Locations",
        key_themes=["Ancient City", "Radiants"],
        adventure_hooks=["Reactivate the crystal pillar.", "Explore the oathgates."],
        body_text="Urithiru is a massive city of stone constructed high in the mountains.",
        example_text="Shallan: The tower is breathtaking.",
    )
    md_1 = lore.to_markdown()
    parts_1 = md_1.split("---\n", 2)
    body_clean_1, ex_clean_1 = _parse_vault_markdown_body(parts_1[2])

    assert "### Lore & Worldbuilding" not in body_clean_1
    assert "### Adventure Hooks" not in body_clean_1
    assert "Urithiru is a massive city" in body_clean_1
    assert "Shallan: The tower is breathtaking." in (ex_clean_1 or "")

    lore_reloaded = OKFLoreEntry(
        schema_version="1.0.0",
        sourcebook="Roshar Guide",
        name="Urithiru",
        category="Locations",
        key_themes=["Ancient City", "Radiants"],
        adventure_hooks=["Reactivate the crystal pillar.", "Explore the oathgates."],
        body_text=body_clean_1,
        example_text=ex_clean_1,
    )
    md_2 = lore_reloaded.to_markdown()
    # Sections must appear exactly once
    assert md_2.count("### Lore & Worldbuilding") == 1
    assert md_2.count("### Adventure Hooks") == 1
    assert md_2.count("### Example Play") == 1

    # 2. OKFAdventureNode idempotency
    node = OKFAdventureNode(
        schema_version="1.0.0",
        sourcebook="Chasm Solo",
        name="Chasm Ambush",
        category="Act 1",
        node_id="A1",
        read_aloud="Red eyes gleam in the dark chasm.",
        body_text="Three chasmfiends approach the expedition party.",
        skill_checks=[{"skill": "Athletics", "dc": 14, "success": "Climb ledge"}],
        choices=[{"option": "Run", "target_node": "A2"}],
    )
    node_md_1 = node.to_markdown()
    node_parts_1 = node_md_1.split("---\n", 2)
    node_body_1, _ = _parse_vault_markdown_body(node_parts_1[2])

    assert "### Read-Aloud" not in node_body_1
    assert "### Scene & Mechanics" not in node_body_1
    assert "### Skill Checks" not in node_body_1
    assert "### Choices & Branches" not in node_body_1
    assert "Three chasmfiends approach" in node_body_1


def test_parse_gemini_json_payload_nested_arrays_adventure_node():
    raw_response = (
        "[\n"
        "  {\n"
        '    "schema_version": "1.0.0",\n'
        '    "sourcebook": "Cosmere RPG - The First Step",\n'
        '    "type": "adventure_node",\n'
        '    "name": "Search Gear",\n'
        '    "category": "Part 1",\n'
        '    "node_id": "A",\n'
        '    "read_aloud": "You rummage through your gear.",\n'
        '    "body_text": "Choose your weapon.",\n'
        '    "choices": [\n'
        '      {"option": "A weapon", "target_node": "A1", "condition": null},\n'
        '      {"option": "A spanreed", "target_node": "A2", "condition": null}\n'
        "    ],\n"
        '    "skill_checks": [\n'
        '      {"skill": "Athletics", "dc": 10, "success": "You climb.", "failure": "You slip."}\n'
        "    ]\n"
        "  }\n"
        "]"
    )
    items = parse_gemini_json_payload(raw_response)
    assert len(items) == 1
    assert items[0]["type"] == "adventure_node"
    assert items[0]["name"] == "Search Gear"
    assert items[0]["node_id"] == "A"
    assert len(items[0]["choices"]) == 2
    assert items[0]["choices"][0]["target_node"] == "A1"
    assert len(items[0]["skill_checks"]) == 1
    assert items[0]["skill_checks"][0]["dc"] == 10
