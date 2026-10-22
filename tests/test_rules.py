from ttrpg_markdown_pipeline.rules.cosmere import (
    ADVENTURE_KEYWORDS,
    ADVENTURE_PROMPT,
    LORE_KEYWORDS,
    LORE_PROMPT,
    MECHANICS_KEYWORDS,
    patch_cosmere_rules,
)


def test_patch_cosmere_rules():
    sample = (
        "Actions (). Reactions (). Free Actions ().\n"
        "Opportunity symbol () and Complication symbol ().\n"
        "As , you can move.\n"
        "action as . Before you take damage\n"
        "Recover action as .\n"
        "## Flowchart Step 8\n"
        "## Cadmium Allomancy Era 2\n"
        "## Tier 2\n"
        "Activation:\n"
        "use the Interact action as ▷ to draw this weapon.\n"
        "The GM can spend to cause your armor to crack.\n"
        "use 2 to attach and light a fuse.\n"
        "| Calibration | expend the | - |\n"
        "| Suppressor | ammunition from that chamber. Only sensed within |\n"
        "Implant Spike (3) and Remove Spike (▶)\n"
        "can spend to appeal to their own sense of duty\n"
        "can spend to lessen your grip on the handle\n"
        "ask you to use to do so (via the Use a Skill action in chapter 10).\n"
        "If you're making a test as part of another action, you don't need to use .\n"
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
    assert "## Flowchart Step\n" in patched
    assert "## Cadmium Allomancy Era 2" in patched
    assert "## Tier 2" in patched
    assert "Activation: [Passive / Varies]" in patched
    assert "use the Interact action as [Free Action] to draw this weapon." in patched
    assert "The GM can spend [Complication] to cause your armor to crack." in patched
    assert "use [2 Actions] to attach and light a fuse." in patched
    assert "| Calibration | expend the ammunition from that chamber. | - |" in patched
    assert "| Suppressor | Only sensed within |" in patched
    assert "Implant Spike [3 Actions] and Remove Spike [1 Action]" in patched
    assert "can spend [Opportunity] to appeal to their own sense of duty" in patched
    assert "can spend [Complication] to lessen your grip on the handle" in patched
    assert "ask you to use [1 Action] to do so (via the Use a Skill action in chapter 10)." in patched
    assert "If you're making a test as part of another action, you don't need to use [1 Action]." in patched


def test_mechanics_keyword_matching():
    assert any(kw in "04-Heroic_Paths".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Combat & Action Economy".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Metallic Arts".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Adversaries".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "06-Chapter 6 - Surges".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "11-Chapter 11 - Conversations".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "12-Chapter 12 - Endeavors".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "17-Appendix - Animal Companions".lower() for kw in MECHANICS_KEYWORDS)
    assert not any(kw in "World of Scadrial Overview".lower() for kw in MECHANICS_KEYWORDS)
    # Part does not trigger mechanics
    assert not any(kw in "01-Part 1 - Alethi Ambush".lower() for kw in MECHANICS_KEYWORDS)


def test_lore_and_adventure_keywords_and_prompts():
    assert any(kw in "World of Roshar".lower() for kw in LORE_KEYWORDS)
    assert any(kw in "Factions and Cultures".lower() for kw in LORE_KEYWORDS)
    assert any(kw in "Part 1 - Alethi Ambush".lower() for kw in ADVENTURE_KEYWORDS)
    assert any(kw in "Scene 3 - The Chasm".lower() for kw in ADVENTURE_KEYWORDS)

    assert "key_themes" in LORE_PROMPT
    assert "adventure_hooks" in LORE_PROMPT
    assert "adventure_node" in ADVENTURE_PROMPT
    assert "skill_checks" in ADVENTURE_PROMPT
