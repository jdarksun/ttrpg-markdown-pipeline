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
        "Activation:\n"
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
    assert "## Flowchart Step" in patched
    assert "Activation: [Passive / Varies]" in patched


def test_mechanics_keyword_matching():
    assert any(kw in "04-Heroic_Paths".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Combat & Action Economy".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Metallic Arts".lower() for kw in MECHANICS_KEYWORDS)
    assert any(kw in "Adversaries".lower() for kw in MECHANICS_KEYWORDS)
    assert not any(kw in "World of Scadrial Overview".lower() for kw in MECHANICS_KEYWORDS)
