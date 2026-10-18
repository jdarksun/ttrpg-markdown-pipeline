from ttrpg_markdown_pipeline.rules.cosmere import (
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


def test_mechanics_keyword_matching():
    assert any(kw in "04-Heroic_Paths".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Combat & Action Economy".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Metallic Arts".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Adversaries".lower() for kw in MECHANICS_KEYWORDS)
    assert not any(kw in "World of Scadrial Overview".lower() for kw in MECHANICS_KEYWORDS)
