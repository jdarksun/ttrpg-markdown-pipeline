"""Comprehensive parameterized test suite for Cosmere rules repairs and regex patterns."""

import re

import pytest

from ttrpg_markdown_pipeline.rules.cosmere import (
    MECHANICS_KEYWORDS,
    UNIVERSAL_INLINE_FIXES,
    patch_cosmere_rules,
)


@pytest.mark.parametrize(
    ("input_text", "expected_output"),
    [
        # Stances & Actions
        ("enter as : an action", "enter as [Free Action]: an action"),
        ("enter another stance you know as ▷ to defend", "enter another stance you know as [Free Action] to defend"),
        ("enter another stance you know as : now", "enter another stance you know as [Free Action]: now"),
        ("Grapple or Shove as (instead of) normal", "Grapple or Shove as [1 Action] (instead of [2 Actions]) normal"),
        # Reactions
        ("without spending ↻ to counter", "without spending [Reaction] to counter"),
        ("gain an additional ↻ each round", "gain an additional [Reaction] each round"),
        ("spending ↻ when struck", "spending [Reaction] when struck"),
        # Action Grants & Movement
        ("spend an additional to Disengage quickly", "spend an additional [1 Action] to Disengage quickly"),
        (
            "must spend an additional when they draw weapons",
            "must spend an additional [1 Action] when they draw weapons",
        ),
        (
            "gain that can be spent only on the Brace stance",
            "gain [Free Action] that can be spent only on the Brace stance",
        ),
        (
            "gain that can be spent only to Strike directly",
            "gain [Free Action] that can be spent only to Strike directly",
        ),
        ("use their Rousing Presence as . Next turn", "use their Rousing Presence as [Free Action]. Next turn"),
        ("use your Field Medicine as . Then", "use your Field Medicine as [Free Action]. Then"),
        # Chapter 3 Specifics
        ("ask you to use to do so today", "ask you to use [1 Action] to do so today"),
        ("don't need to use . Always active", "don't need to use [1 Action]. Always active"),
        # Chapter 4 Specifics
        ("gain for cognitive tests this encounter", "gain [2 Actions] for cognitive tests this encounter"),
        ("gain for physical tests this encounter", "gain [2 Actions] for physical tests this encounter"),
        ("gain for spiritual tests this encounter", "gain [2 Actions] for spiritual tests this encounter"),
        (
            "use both to make an additional contribution to the goal",
            "use both [2 Actions] to make an additional contribution to the goal",
        ),
        ("spend 1 focus or to apply leverage", "spend 1 focus or [Opportunity] to apply leverage"),
        ("to on the plot die roll", "to [Opportunity] on the plot die roll"),
        ("Spend from False Flattery immediately", "Spend [Opportunity] from False Flattery immediately"),
        # Chapter 5 Specifics
        ("Store actions as . Then relax", "Store actions as [Free Action]. Then relax"),
        ("Tap actions as . In combat", "Tap actions as [Free Action]. In combat"),
        (
            "removed a piece of your metalmind (as) and stowed it",
            "removed a piece of your metalmind (as [1 Action]) and stowed it",
        ),
        ("gain for tapping your attribute", "gain [1 Action] for tapping your attribute"),
        # Chapter 7 Specifics
        ("action as ▷ to draw your sidearm", "action as [Free Action] to draw your sidearm"),
        ("can spend to cause it to break on hit", "can spend [Complication] to cause it to break on hit"),
        ("GM can spend to cause your armor to buckle", "GM can spend [Complication] to cause your armor to buckle"),
        ("can spend to cause the target to fall prone", "can spend [Opportunity] to cause the target to fall prone"),
        ("spend from an attack roll", "spend [Complication] from an attack roll"),
        ("use 2 to attach and light the wick", "use [2 Actions] to attach and light the wick"),
        ("can use to make an Athletics test instead", "can use [1 Action] to make an Athletics test instead"),
        ("can use to throw this pouch across the room", "can use [1 Action] to throw this pouch across the room"),
        ("used as to light abundant fuel quickly", "used as [1 Action] to light abundant fuel quickly"),
        ("same duration by using . Continuous", "same duration by using [1 Action]. Continuous"),
        # Chapter 7 Table Spill
        ("| Calibration | expend the | - |", "| Calibration | expend the ammunition from that chamber. | - |"),
        ("| Suppressor | ammunition from that chamber. Senses |", "| Suppressor | Senses |"),
        # Chapter 8 Specifics
        ("Implant Spike (3) into flesh", "Implant Spike [3 Actions] into flesh"),
        ("Remove Spike (▶) with force", "Remove Spike [1 Action] with force"),
        (
            "can spend to appeal to their own sense of honor",
            "can spend [Opportunity] to appeal to their own sense of honor",
        ),
        ("can spend to lessen your grip on the rope", "can spend [Complication] to lessen your grip on the rope"),
    ],
)
def test_universal_inline_fixes_patterns(input_text: str, expected_output: str):
    """Verifies that every inline regex pattern accurately mutates text to canonical OKF symbols."""
    patched = input_text
    for pattern, replacement in UNIVERSAL_INLINE_FIXES.items():
        patched = re.sub(pattern, replacement, patched)
    assert patched == expected_output


@pytest.mark.parametrize(
    ("title", "is_mechanics"),
    [
        ("04-Heroic_Paths.pdf", True),
        ("05-Metalborn_Paths.pdf", True),
        ("06-Metallic_Arts.pdf", True),
        ("07-Items_and_Equipment.pdf", True),
        ("08-Adversaries.pdf", True),
        ("10-Combat_and_Action_Economy.pdf", True),
        ("00-Introduction.pdf", False),
        ("01-World_of_Scadrial.pdf", False),
        ("12-Acknowledgments.pdf", False),
    ],
)
def test_mechanics_keyword_matching_parametrized(title: str, is_mechanics: bool):
    """Verifies keyword routing for mechanics chapters."""
    matched = any(kw in title.lower() for kw in MECHANICS_KEYWORDS)
    assert matched is is_mechanics


def test_full_patch_cosmere_rules_suite():
    """Integration test verifying full patch_cosmere_rules execution."""
    sample = (
        "Actions ().\n"
        "Reactions ().\n"
        "Free Actions ().\n"
        "Opportunity symbol () and Complication symbol ().\n"
        "requires one action, it's labeled ; "
        "if it requires two actions, it's labeled ; "
        "and if it requires three actions, it's labeled .\n"
        "As , you can sprint.\n"
        "action as . Before you take damage\n"
        "Recover action as .\n"
        "Interact action as .\n"
        "## Fast Tapping 2\n"
        "## Cadmium Allomancy Era 2\n"
        "## Tier 2\n"
        "Activation:\n"
    )
    result = patch_cosmere_rules(sample)

    assert "Actions ([1 / 2 / 3 Actions])." in result
    assert "Reactions ([Reaction])." in result
    assert "Free Actions ([Free Action])." in result
    assert "Opportunity symbol ([Opportunity])" in result
    assert "Complication symbol ([Complication])" in result
    assert (
        "requires one action, it's labeled [1 Action]; "
        "if it requires two actions, it's labeled [2 Actions]; "
        "and if it requires three actions, it's labeled [3 Actions]."
    ) in result
    assert "As [1 Action], you can sprint." in result
    assert "action as [Reaction]. Before you take damage" in result
    assert "Recover action as [1 Action]." in result
    assert "Interact action as [1 Action]." in result
    assert "## Fast Tapping\n" in result
    assert "## Cadmium Allomancy Era 2\n" in result
    assert "## Tier 2\n" in result
    assert "Activation: [Passive / Varies]" in result
