"""Tests for OKF Pydantic models."""

import yaml

from ttrpg_markdown_pipeline.models import (
    OKFConcept,
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
    assert md.endswith("Allomancy is the art of burning metals.\n")

    # Frontmatter can be parsed as valid yaml
    parts = md.split("---\n")
    frontmatter_dict = yaml.safe_load(parts[1])
    assert frontmatter_dict["name"] == "Allomancy Overview"
    assert "body_text" not in frontmatter_dict


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
