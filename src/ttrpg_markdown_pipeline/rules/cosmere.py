"""Cosmere RPG specific rules, keywords, prompts, and text patches."""

import re

# Chapters containing these words in their title trigger the Full Pipeline (Docling + Gemini + Merge)
MECHANICS_KEYWORDS = [
    "path",  # Heroic Paths, Metalborn Paths
    "art",  # Metallic Arts
    "combat",  # Combat
    "item",  # Items & Equipment
    "adversar",  # Adversaries / Bestiary
]

DEFAULT_PROMPT = """
You are a precision TTRPG rules extraction engine.
Analyze this Cosmere RPG rules section and extract all mechanical concepts, talents, actions, items, and rules into a STRICT JSON list of objects matching the Open Knowledge Format (OKF) schema.

CRITICAL INSTRUCTIONS:
1. Output ONLY a valid JSON array of objects. Do not wrap with prose, introduction, or conversational text. Fenced markdown json (```json ... ```) is acceptable.
2. For each extracted concept, output an object with:
   - "schema_version": "1.0.0"
   - "sourcebook": The sourcebook or publication identifier (e.g. "Mistborn World Guide", "Stormlight RPG")
   - "type": One of "talent", "weapon", "armor", "item", "rule", or "adversary"
   - "name": Canonical name of the concept (e.g. "Pewterarm Weaponcraft", "Longsword", "Disengage")
   - "category": Parent tree, group, or section (e.g. "Pewter Allomancy", "Light Weaponry", "Combat Actions")
   - Concept-specific fields:
     * For "talent": "prerequisites" (string or null) and "activation" (standardized: "[1 Action]", "[2 Actions]", "[3 Actions]", "[Reaction]", "[Free Action]", "[Special Activation]", or "[Passive]")
     * For "weapon": "damage", "range", "traits" (list of strings), "cost"
     * For "armor": "deflect", "traits" (list of strings), "cost"
     * For "item": "cost", "weight"
     * For "rule": "action_cost" (standardized activation), "trigger"
     * For "adversary": "tier", "role"
   - "body_text": The complete rules description and mechanical effects. Do NOT summarize or omit rules nuances.
   - "example_text": Any gameplay dialogue transcripts, play examples, or in-character banter illustrating the rule (or null if none). Keep pure mechanics in body_text.

Strict Icon Translation Rules for body_text & activation:
- Single filled diamond -> `[1 Action]`
- Two diamonds -> `[2 Actions]`
- Three diamonds -> `[3 Actions]`
- Clockwise loop / circular arrow -> `[Reaction]`
- Open / winged diamond -> `[Free Action]`
- Star icon (★) or badge -> `[Special Activation]`
- Figure-8 / infinity symbol -> `[Passive]`
- Crossed keys / sunburst icon -> `[Opportunity]`
- Spiked skull / complication icon -> `[Complication]`
"""  # noqa: E501

# Case-insensitive / normalized inline phrase fixes for Cosmere rulebooks
UNIVERSAL_INLINE_FIXES = {
    # Stances & Actions
    r"enter as :": "enter as [Free Action]:",
    r"enter another stance you know as ▷": "enter another stance you know as [Free Action]",
    r"enter another stance you know as :": "enter another stance you know as [Free Action]:",
    r"Grapple or Shove as \(instead of\)": "Grapple or Shove as [1 Action] (instead of [2 Actions])",
    # Reactions
    r"without spending ↻": "without spending [Reaction]",
    r"gain an additional ↻": "gain an additional [Reaction]",
    r"spending ↻": "spending [Reaction]",
    # Action Grants & Movement
    r"spend an additional to Disengage": "spend an additional [1 Action] to Disengage",
    r"must spend an additional when they draw": "must spend an additional [1 Action] when they draw",
    r"gain that can be spent only on the Brace": "gain [Free Action] that can be spent only on the Brace",
    r"gain that can be spent only to Strike": "gain [Free Action] that can be spent only to Strike",
    r"use their Rousing Presence as \.": "use their Rousing Presence as [Free Action].",
    r"use your Field Medicine as \.": "use your Field Medicine as [Free Action].",
    # Chapter 3 Specifics (Skills as Actions)
    r"ask you to use to do so": "ask you to use [1 Action] to do so",
    r"don't need to use \.": "don't need to use [1 Action].",
    # Chapter 4 Specifics (Agent & Scholar inline gaps)
    r"gain for cognitive tests": "gain [2 Actions] for cognitive tests",
    r"gain for physical tests": "gain [2 Actions] for physical tests",
    r"gain for spiritual tests": "gain [2 Actions] for spiritual tests",
    r"use both to make an additional contribution": "use both [2 Actions] to make an additional contribution",
    r"spend 1 focus or to apply": "spend 1 focus or [Opportunity] to apply",
    r"to on the plot die": "to [Opportunity] on the plot die",
    r"Spend from False Flattery": "Spend [Opportunity] from False Flattery",
    # Chapter 5 Specifics
    r"##\s*\)\s*Drink Vial\s*\(": "### Drink Vial `[1 Action]`",
    r"[Ss]tore actions as \.": "Store actions as [Free Action].",
    r"[Tt]ap actions as \.": "Tap actions as [Free Action].",
    r"removed a piece of your metalmind \(as\)\s*and": "removed a piece of your metalmind (as [1 Action]) and",
    r"[Ss]pend 2 focus to gain\s*,\s*which you can only use": (
        "Spend 2 focus to gain [1 Action], which you can only use"
    ),
    r"gain for tapping your": "gain [1 Action] for tapping your",
    # Chapter 7 Specifics (Items, Equipment & Traits)
    r"action as ▷ to draw": "action as [Free Action] to draw",
    r"can spend to cause it to break": "can spend [Complication] to cause it to break",
    r"GM can spend to cause your armor": "GM can spend [Complication] to cause your armor",
    r"can spend to cause the target": "can spend [Opportunity] to cause the target",
    r"spend from an attack": "spend [Complication] from an attack",
    r"use 2 to attach and light": "use [2 Actions] to attach and light",
    r"can use to make an Athletics test": "can use [1 Action] to make an Athletics test",
    r"can use to throw this pouch": "can use [1 Action] to throw this pouch",
    r"used as to light abundant fuel": "used as [1 Action] to light abundant fuel",
    r"same duration by using \.": "same duration by using [1 Action].",
    # Chapter 7 Table Spill Fixes
    r"expend the\s*\|\s*-\s*\|": "expend the ammunition from that chamber. | - |",
    r"\|\s*Suppressor\s*\|\s*ammunition from that chamber\.\s*": "| Suppressor | ",
    # Chapter 8 Specifics (Organizations & Hemalurgy)
    r"Implant Spike \(3\)": "Implant Spike [3 Actions]",
    r"Remove Spike \(▶\)": "Remove Spike [1 Action]",
    r"can spend to appeal to their own sense": "can spend [Opportunity] to appeal to their own sense",
    r"can spend to lessen your grip": "can spend [Complication] to lessen your grip",
}


def patch_cosmere_rules(text: str) -> str:
    """Post-processing regex cleanup specifically for Cosmere RPG Markdown output."""
    # 1. Introduction Action Economy definitions
    text = re.sub(r"Free Actions\s*\(\s*\)\.", "Free Actions ([Free Action]).", text)
    text = re.sub(r"Reactions\s*\(\s*\)\.", "Reactions ([Reaction]).", text)
    text = re.sub(r"(?<!Free )Actions\s*\(\s*\)\.", "Actions ([1 / 2 / 3 Actions]).", text)
    text = re.sub(
        r"requires one action, it's labeled\s*;\s*"
        r"if it requires two actions, it's labeled\s*;\s*"
        r"and if it requires three actions, it's labeled\s*\.",
        "requires one action, it's labeled [1 Action]; "
        "if it requires two actions, it's labeled [2 Actions]; "
        "and if it requires three actions, it's labeled [3 Actions].",
        text,
    )

    # 2. Plot Die Symbols
    text = re.sub(r"Opportunity symbol\s*\(\s*\)", "Opportunity symbol ([Opportunity])", text)
    text = re.sub(r"Complication symbol\s*\(\s*\)", "Complication symbol ([Complication])", text)

    # 3. Mid-sentence Action/Reaction phrasing
    text = re.sub(r"\bAs\s*,\s*you can", "As [1 Action], you can", text)
    text = re.sub(r"action as\s*\.\s*(?=Before you take damage)", "action as [Reaction]. ", text)
    text = re.sub(r"Recover action as\s*\.", "Recover action as [1 Action].", text)
    text = re.sub(r"Interact action as\s*\.", "Interact action as [1 Action].", text)

    # 4. Clean RapidOCR digit artifacts in headings from flowchart icons (e.g. '## Fast Tapping 2')
    # Preserves legitimate numeral suffixes like 'Era 2' or 'Tier 2'
    text = re.sub(r"^(##\s+[A-Za-z\s]+?(?<!\bEra)(?<!\bTier))\s+[28]$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+2\s+([A-Za-z\s]+)$", r"## \1", text, flags=re.MULTILINE)

    # 5. Fix standalone blank 'Activation:' lines
    text = re.sub(r"^Activation:\s*$", "Activation: [Passive / Varies]", text, flags=re.MULTILINE)

    # 6. Apply universal inline icon and phrase repairs
    for raw_regex, fix in UNIVERSAL_INLINE_FIXES.items():
        text = re.sub(raw_regex, fix, text)

    return text
