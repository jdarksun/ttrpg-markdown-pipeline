"""Tests for OKF Pydantic models."""

import yaml

from ttrpg_markdown_pipeline.models import (
    OKFAdventureNode,
    OKFConcept,
    OKFLoreEntry,
    OKFRule,
    OKFTalent,
    OKFWeapon,
    sanitize_activation,
)


def test_sanitize_activation():
    assert sanitize_activation("1 action") == "[1 Action]"
    assert sanitize_activation("[3 actions]") == "[3 Actions]"
    assert sanitize_activation("reaction") == "[Reaction]"
    assert sanitize_activation("free action") == "[Free Action]"
    assert sanitize_activation("special") == "[Special Activation]"
    assert sanitize_activation("passive") == "[Passive]"
    assert sanitize_activation("always active") == "[Passive]"
    assert sanitize_activation("[Custom]") == "[Custom]"


def test_okf_concept_to_markdown():
    concept = OKFConcept(
        schema_version="1.0.0",
        type="concept",
        sourcebook="Mistborn World Guide",
        name="Allomancy Overview",
        category="Metallic Arts",
        body_text="Allomancy is the art of burning metals.",
    )

    md = concept.to_markdown()
    assert md.startswith("---\n")
    assert "schema_version: 1.0.0" in md
    assert "type: concept" in md
    assert "sourcebook: Mistborn World Guide" in md
    assert "name: Allomancy Overview" in md
    assert "category: Metallic Arts" in md
    assert "### Mechanics\n\nAllomancy is the art of burning metals." in md
    assert md.endswith("Allomancy is the art of burning metals.\n")

    # Frontmatter can be parsed as valid yaml
    parts = md.split("---\n")
    frontmatter_dict = yaml.safe_load(parts[1])
    assert frontmatter_dict["name"] == "Allomancy Overview"
    assert "body_text" not in frontmatter_dict
    assert "example_text" not in frontmatter_dict


def test_okf_concept_to_markdown_with_example():
    concept = OKFConcept(
        schema_version="1.0.0",
        type="rule",
        sourcebook="DCC RPG",
        name="Attack",
        category="Combat",
        body_text="A crawler strikes at a Mob with a weapon.",
        example_text="Joe: Roll your d20 to hit.\nPaige: Got a 16!",
    )

    md = concept.to_markdown()
    assert "### Mechanics\n\nA crawler strikes at a Mob with a weapon." in md
    assert "### Example Play\n\nJoe: Roll your d20 to hit.\nPaige: Got a 16!" in md

    # Neither body_text nor example_text should appear in frontmatter
    parts = md.split("---\n")
    frontmatter_dict = yaml.safe_load(parts[1])
    assert "body_text" not in frontmatter_dict
    assert "example_text" not in frontmatter_dict


def test_okf_talent_normalization():
    talent = OKFTalent(
        sourcebook="Mistborn World Guide",
        name="Steel Bubble",
        category="Steel Allomancy",
        prerequisites="Steel 2+",
        activation="2 actions",
        body_text="You create a protective bubble of repelling force.",
    )

    assert talent.activation == "[2 Actions]"
    assert talent.prerequisites == "Steel 2+"
    assert talent.type == "talent"

    md = talent.to_markdown()
    assert (
        "activation: '[2 Actions]'" in md
        or 'activation: "[2 Actions]"' in md
        or "activation: '[2 Actions]'" in md
        or "[2 Actions]" in md
    )
    assert "prerequisites: Steel 2+" in md


def test_okf_talent_clean_none_prereqs():
    talent = OKFTalent(
        sourcebook="Mistborn World Guide",
        name="Iron Stance",
        category="Iron Allomancy",
        prerequisites=" None ",
        activation="passive",
    )
    assert talent.prerequisites is None
    assert talent.activation == "[Passive]"


def test_okf_weapon():
    weapon = OKFWeapon(
        sourcebook="Mistborn World Guide",
        name="Dueling Cane",
        category="Light Weaponry",
        damage="1d6 physical",
        range="Melee",
        traits=["Discreet", "Finesse"],
        cost="15 boxing",
        body_text="A discreet weapon favored by nobility.",
    )
    assert weapon.type == "weapon"
    assert weapon.traits == ["Discreet", "Finesse"]
    assert "damage: 1d6 physical" in weapon.to_markdown()


def test_okf_rule_action_cost():
    rule = OKFRule(
        sourcebook="Mistborn World Guide",
        name="Disengage",
        category="Movement Actions",
        action_cost="1 action",
        body_text="You carefully withdraw from close combat.",
    )
    assert rule.type == "rule"
    assert rule.action_cost == "[1 Action]"


def test_okf_lore_entry():
    lore = OKFLoreEntry(
        type="faction",
        sourcebook="Stormlight World Guide",
        name="Ghostbloods",
        category="Secret Societies",
        key_themes=["Cosmere conspiracy", "Survival at any cost"],
        adventure_hooks=[
            "A contact disappears leaving behind a silver coin.",
            "A warehouse contains unrefined gemstones from another world.",
        ],
        body_text="An enigmatic organization originating from Scadrial seeking Investiture across the Cosmere.",
    )

    md = lore.to_markdown()
    assert "type: faction" in md
    assert "Ghostbloods" in md
    assert "key_themes:" in md
    assert "Cosmere conspiracy" in md
    assert "### Lore & Worldbuilding" in md
    assert "An enigmatic organization originating from Scadrial" in md
    assert "### Adventure Hooks" in md
    assert "- A contact disappears leaving behind a silver coin." in md


def test_okf_adventure_node():
    node = OKFAdventureNode(
        sourcebook="Stormlight RPG - The First Step",
        module_name="The First Step: Solo Edition",
        node_id="A1",
        name="Alethi Ambush Opening",
        category="Part 1",
        read_aloud="The sound of thunder shakes the canyon as arrows rain down from above.",
        body_text="Parshendi skirmishers ambush the caravan flanks. Crawlers must react immediately.",
        skill_checks=[
            {
                "skill": "Athletics",
                "dc": 14,
                "success": "Reach cover unharmed",
                "failure": "Take 4 keen damage",
            }
        ],
        state_mutations=["Resources -1", "Condition: Alert"],
        choices=[
            {"option": "Charge the archers", "target_node": "A2"},
            {"option": "Protect the wagon", "target_node": "A3", "condition": "Requires shield"},
        ],
        journal_prompts=["How does your character react to the sudden violence of the ambush?"],
    )

    md = node.to_markdown()
    assert "type: adventure_node" in md
    assert "node_id: A1" in md
    assert "### Read-Aloud" in md
    assert "> The sound of thunder shakes the canyon" in md
    assert "### Scene & Mechanics" in md
    assert "Parshendi skirmishers ambush the caravan flanks." in md
    assert "### Skill Checks" in md
    assert "- **Athletics** (DC 14): Success -> Reach cover unharmed; Failure -> Take 4 keen damage" in md
    assert "### Choices & Branches" in md
    assert "- Charge the archers -> Go to **A2**" in md
    assert "- Protect the wagon *(Requires shield)* -> Go to **A3**" in md
    assert "### Journal Prompts" in md
    assert "- *How does your character react to the sudden violence of the ambush?*" in md
