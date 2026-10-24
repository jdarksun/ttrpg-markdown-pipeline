"""Cosmere RPG specific rules, keywords, prompts, and text patches."""

import re

# ==============================================================================
# FIDELITY-FIRST DENYLIST ARCHITECTURE
# ==============================================================================
# TTRPG rulebooks frequently interleave critical mechanics, character creation
# tables, GM adjudication procedures, and worldbuilding lore inside chapters with
# non-obvious titles (e.g. "Introduction", "Gamemastering", "The Next Step").
#
# Rather than risking dropped rules through a restrictive title allowlist, the
# pipeline uses a metadata-only denylist (CHAPTER_DENYLIST) to exclude pure front/back
# matter (Credits, Table of Contents, Index, Character Sheets). All non-denylisted
# chapters route to chap_mode = "mechanics" (UNIFIED_PROMPT) by default, extracting
# both mechanical rules and worldbuilding entities with 0% missed rules.
#
# ROLE OF KEYWORD SETS:
# - MECHANICS_KEYWORDS, LORE_KEYWORDS, and ADVENTURE_KEYWORDS are used ONLY when
#   specialized modes (--include-lore or --adventure-mode) are explicitly passed to
#   route pure setting or adventure module chapters to specialized prompts (LORE_PROMPT
#   or ADVENTURE_PROMPT) without overriding explicit mechanics chapters.
# ==============================================================================

# Chapters matching these terms are pure front/back metadata and skip Gemini Vision & OKF shredding
CHAPTER_DENYLIST = [
    "credits",
    "contents",
    "table of contents",
    "acknowledgments",
    "acknowledgements",
    "character sheet",
    "index",
    "glossary",
    "backertable",
]


def is_substantive_chapter(title: str) -> bool:
    """Returns True if the chapter is substantive game content (not on CHAPTER_DENYLIST)."""
    lower_title = title.lower()
    return not any(denied in lower_title for denied in CHAPTER_DENYLIST)


# Chapters containing these words in their title are explicitly mechanical (used for appendix disambiguation)
MECHANICS_KEYWORDS = [
    # Paths, Classes, and Features
    "path",  # Heroic Paths, Radiant Paths, Metalborn Paths
    "class",  # Character Classes
    "feat",  # Feats & Features
    "arts",  # Metallic Arts, Martial Arts
    "surge",  # Surges & Surgebinding
    "power",  # Powers & Psionics
    "spell",  # Spells & Spellcasting
    # Combat, Actions, and Encounters
    "combat",  # Combat & Action Economy
    "action",  # Actions & Reactions
    "endeavor",  # Endeavors
    "conversation",  # Conversations
    # Equipment, Items, and Gear
    "item",  # Items & Equipment
    "equipment",  # Equipment & Gear
    "weapon",  # Weapons
    "armor",  # Armor
    "gear",  # Adventuring Gear
    # Adversaries and Creatures
    "adversar",  # Adversaries
    "bestiary",  # Bestiary
    "monster",  # Monsters
    "companion",  # Animal Companions
    # Characters, Origins, and Ancestries
    "origin",  # Origins & Cultures
    "ancestr",  # Ancestries & Heritages
    "heritage",  # Heritages
    "species",  # Species
    "race",  # Races
    "expertise",  # Cultural & Utility Expertises
    # Core Statistics and Rules
    "statistic",  # Character Statistics
    "attribute",  # Attributes
    "skill",  # Skills
    "rule",  # Core Rules
    "adventuring",  # Adventuring & Environmental Rules
    "condition",  # Conditions & Afflictions
    "hazard",  # Environmental Hazards
]

# Chapters containing these words describe worldbuilding, geography, culture, and factions
LORE_KEYWORDS = [
    "world",
    "lore",
    "history",
    "faction",
    "culture",
    "setting",
    "gazetteer",
    "atlas",
    "cosmology",
    "organization",
]

# Chapters or section titles describing modular/procedural adventure sequences
ADVENTURE_KEYWORDS = [
    "part ",
    "scene",
    "act ",
    "encounter",
    "episode",
    "solo",
    "adventure module",
]

UNIFIED_PROMPT = """
You are a precision TTRPG rules and worldbuilding extraction engine.
Analyze this TTRPG section and extract all mechanical concepts (talents, actions, items, weapons, armor, adversaries, rules, character creation/advancement procedures, GM adjudication procedures) AND any distinct worldbuilding entities (cultures, factions, historical eras, locations, lore) into a STRICT JSON list of objects matching the Open Knowledge Format (OKF) schema.

CRITICAL INSTRUCTIONS:
1. Output ONLY a valid JSON array of objects. Do not wrap with prose, introduction, or conversational text. Fenced markdown json (```json ... ```) is acceptable.
2. For each extracted concept, output an object with:
   - "schema_version": "1.0.0"
   - "sourcebook": The sourcebook or publication identifier (e.g. "Mistborn World Guide", "Stormlight RPG")
   - "type": One of "talent", "weapon", "armor", "item", "rule", "adversary", "lore", "faction", or "location"
   - "name": Canonical name of the concept or entity (e.g. "Pewterarm Weaponcraft", "Longsword", "Disengage", "Step 3: Attributes", "Ghostbloods")
   - "category": Parent tree, group, culture, or section (e.g. "Pewter Allomancy", "Light Weaponry", "Combat Actions", "Character Creation", "Roshar Factions")
   - Concept-specific fields:
     * For "talent": "prerequisites" (string or null) and "activation" (standardized: "[1 Action]", "[2 Actions]", "[3 Actions]", "[Reaction]", "[Free Action]", "[Special Activation]", or "[Passive]")
     * For "weapon": "damage", "range", "traits" (list of strings), "cost"
     * For "armor": "deflect", "traits" (list of strings), "cost"
     * For "item": "cost", "weight"
     * For "rule": "action_cost" (standardized activation, or null for passive/procedural rules), "trigger" (string or null)
     * For "adversary": "tier", "role"
     * For "lore", "faction", or "location": "key_themes" (list of 2-5 thematic tags) and "adventure_hooks" (list of 2-4 plot hooks or encounter seeds)
   - "body_text": The complete, verbatim rules description, step-by-step procedure, stat block, or lore entry. Include any reference or progression tables formatted as Markdown tables inside body_text. Do NOT summarize, abbreviate, or omit nuances, numbers, or allocation limits. Exclude page footers and artist credits.
   - "example_text": Any gameplay dialogue transcripts, play examples, or in-world quotes/epigraphs illustrating the concept (or null if none). Extract all shaded/boxed gameplay transcripts or dialogue examples (e.g., lines starting with "GM:" or "PlayerName (playing Character):") into example_text verbatim rather than omitting them or leaving them inside body_text. Keep all mechanical stats, formulas, and rules in body_text.
3. PROCEDURAL RULES & TABLES: Every procedural section, numbered creation/advancement step (e.g. "Character Creation Steps", "Step 1: Origins", "Step 2: Starting Path", "Step 3: Attributes", "Step 4: Skills and Expertises", "Step 5: Talents", "Step 6: Equipment", "Step 7: Story", "Step 8: Final Calculations", "Character Advancement", "Gaining a Level"), and core subsystem rule MUST be extracted as a `"type": "rule"` object with its complete verbatim instructions and Markdown tables in `body_text`.
4. IGNORE SAMPLE CHARACTER SHEETS & PREVIEW STUBS: Do NOT extract individual talents, weapons, or armor shown on filled-in example character sheet illustrations or 1-line "at a glance" summary tables as standalone `"talent"`, `"weapon"`, or `"armor"` objects (instead, keep summary tables inside the parent rule's `body_text`). Similarly, do NOT extract 1-sentence passing mentions or example list items of factions, locations, or cultures inside mechanics/character-creation chapters as standalone `"lore"`, `"faction"`, or `"location"` objects; only extract a worldbuilding entity when the page contains a dedicated heading or substantive multi-sentence section describing that entity.
5. HEADING GRANULARITY (## vs ###) & NON-DUPLICATION:
   - 5a. Cohesive Procedures & Multi-Part Rules (Group under ##): When a ## section represents a single cohesive procedure, numbered creation/advancement step (e.g., "Step 1: Origins", "Step 5: Talents"), or mechanical resolution rule whose ### subheadings are sequential sub-steps, modifiers, or outcomes of that rule (e.g., "Opportunities and Complications" with "### Spending an Opportunity", "### Facing a Complication", and "### Complication Bonus"), emit ONE "type": "rule" object named after the parent ## heading and include all of its ### subheadings and text inside its body_text.
   - 5b. Catalogs of Standalone Options/Entities (Split at ###): When a section is a catalog or reference list of discrete, independently usable game elements—such as individual combat actions ("Strike", "Move", "Brace", "Disengage"), individual conditions ("Afflicted", "Empowered", "Prone"), individual talents, weapons, armor, equipment items, or adversary stat blocks—emit each individual entity as its own separate JSON object.
   - 5c. Strict Non-Duplication: NEVER emit both a parent "rule" object containing ### subsections in its body_text AND separate JSON objects for those same ### subsections. Every paragraph of rules text on a page must belong to at most one JSON object.

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

DEFAULT_PROMPT = UNIFIED_PROMPT

LORE_PROMPT = """
You are a precision TTRPG worldbuilding and narrative lore extraction engine.
Analyze this Cosmere RPG setting/lore chapter and extract all narrative entities, factions, historical eras, cultural overviews, and significant locations into a STRICT JSON list of objects matching the Open Knowledge Format (OKF) schema.

CRITICAL INSTRUCTIONS:
1. Output ONLY a valid JSON array of objects. Do not wrap with prose, introduction, or conversational text. Fenced markdown json (```json ... ```) is acceptable.
2. For each extracted lore concept, output an object with:
   - "schema_version": "1.0.0"
   - "sourcebook": The sourcebook or publication identifier (e.g. "Stormlight World Guide", "Mistborn World Guide")
   - "type": One of "lore" (general history, cosmology, or concept), "faction" (organization, order, or political group), or "location" (city, realm, region, or landmark)
   - "name": Canonical name of the entity (e.g. "Ghostbloods", "Shattered Plains", "The Desolations")
   - "category": Parent realm, region, or topic (e.g. "Roshar Factions", "Alethkar Geography", "Historical Eras")
   - "key_themes": A list of 2-5 thematic tags, motifs, or mood keywords (e.g. ["Cosmere intrigue", "Shadow war", "Survival"])
   - "adventure_hooks": A list of 2-4 concrete plot hooks, rumors, or encounter seeds for game masters to use in adventure design
   - "body_text": Comprehensive, rich narrative description, history, philosophy, or geography. Preserve lore depth and nuanced details.
   - "example_text": Any in-world quotes, epigraphs, excerpts, or flavor transcripts illustrating the entity (or null if none).
"""  # noqa: E501

ADVENTURE_PROMPT = """
You are a precision TTRPG adventure module parser and rules extraction engine.
Analyze this adventure module text and extract:
1. Every distinct scene, branching encounter, or decision node into an "adventure_node" object.
2. Any mechanical statblocks, adversaries, unique items, weapons, armor, or special rules into their respective OKF objects.

CRITICAL INSTRUCTIONS:
1. Output ONLY a valid JSON array of objects. Do not wrap with prose, introduction, or conversational text. Fenced markdown json (```json ... ```) is acceptable.
2. For "adventure_node" objects:
   - "schema_version": "1.0.0"
   - "sourcebook": The adventure module title (e.g. "The First Step: Solo Edition", "Stonewalkers")
   - "type": "adventure_node"
   - "name": Descriptive name of the scene or encounter (e.g. "Alethi Ambush Opening", "Chasm Crossing")
   - "category": Scene group, act, or chapter (e.g. "Part 1", "Act 2")
   - "node_id": The alphanumeric identifier or node key (e.g. "A1", "A2", "B4", "Scene 1")
   - "read_aloud": Any boxed text, italics, or narrative meant to be read directly to players (or null if none)
   - "body_text": The GM-facing scene description, tactical setup, hazard details, or narrative resolution
   - "skill_checks": List of objects with {"skill": str, "dc": int | str | null, "success": str | null, "failure": str | null}
   - "state_mutations": List of string modifications to character/party state (e.g. ["Resources -1", "Attribute +1 Speed", "Exhausted [-1]"])
   - "choices": List of branching choices {"option": str, "target_node": str | null, "condition": str | null}
   - "journal_prompts": List of roleplay questions or solo journaling prompts (or empty list if none)
   - "example_text": null

3. For mechanical objects embedded in the adventure (such as adversary encounters, loot, or mechanics):
   - Use "type": "adversary", "weapon", "armor", "item", "rule", or "talent" as appropriate, following standard OKF fields.

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
    r"enter another stance you know as \u25b7": "enter another stance you know as [Free Action]",  # \u25b7: ▷
    r"enter another stance you know as :": "enter another stance you know as [Free Action]:",
    r"Grapple or Shove as \(instead of\)": "Grapple or Shove as [1 Action] (instead of [2 Actions])",
    # Reactions
    r"without spending \u21bb": "without spending [Reaction]",  # \u21bb: ↻
    r"gain an additional \u21bb": "gain an additional [Reaction]",  # \u21bb: ↻
    r"spending \u21bb": "spending [Reaction]",  # \u21bb: ↻
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
    r"action as \u25b7 to draw": "action as [Free Action] to draw",  # \u25b7: ▷
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
    r"Remove Spike \(\u25b6\)": "Remove Spike [1 Action]",  # \u25b6: ▶
    r"can spend to appeal to their own sense": "can spend [Opportunity] to appeal to their own sense",
    r"can spend to lessen your grip": "can spend [Complication] to lessen your grip",
}


def patch_cosmere_rules(text: str) -> str:
    """Post-processing regex cleanup specifically for Cosmere RPG Markdown output."""
    from ttrpg_markdown_pipeline.processors.shredder import clean_extraction_artifacts

    text = clean_extraction_artifacts(text)

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
