from pathlib import Path

from ttrpg_markdown_pipeline.processors.merge import extract_talent_metadata, merge_chapter
from ttrpg_markdown_pipeline.processors.patch import find_final_outputs, patch_file


def test_extract_talent_metadata():
    gemini_sample = """
    ### Iron Stance
    - **Prerequisites:** Strength 14
    - **Activation:** [1 Action]

    ### Steel Bubble (Specialty)
    **Prerequisite:** Iron Stance
    **Activation:** Special Activation

    ## Passive Recovery
    - **Prerequisites:** None
    - **Activation:** Passive

    #### Rapid Strike
    **Prerequisites:** Agility 12
    **Activation:** [Reaction]
    """
    metadata = extract_talent_metadata(gemini_sample)

    assert "iron stance" in metadata
    assert metadata["iron stance"]["raw_name"] == "Iron Stance"
    assert metadata["iron stance"]["prereq"] == "Strength 14"
    assert metadata["iron stance"]["act"] == "[1 Action]"

    # Subtitle in parentheses is stripped in lookup key
    assert "steel bubble" in metadata
    assert metadata["steel bubble"]["raw_name"] == "Steel Bubble"
    assert metadata["steel bubble"]["act"] == "[Special Activation]"

    # 'Passive' mapped to '[Passive]'
    assert "passive recovery" in metadata
    assert metadata["passive recovery"]["act"] == "[Passive]"

    # Lower header levels and reaction activation
    assert "rapid strike" in metadata
    assert metadata["rapid strike"]["act"] == "[Reaction]"


def test_merge_chapter(tmp_path: Path):
    docling_file = tmp_path / "04-Chapter - DOCLING.md"
    gemini_file = tmp_path / "04-Chapter - GEMINI.md"
    out_file = tmp_path / "04-Chapter - MERGED.md"

    docling_text = """
# Heroic Paths

## Steady Aim
Prerequisite: None
Activation:
You take steady aim at a distant foe.
Recover action as .

## Iron Will
You steel your mind against cognitive tests.
gain for cognitive tests.

## Mistborn History
This is pure lore and must not become a talent.

## Alloyed Resonance
- Prerequisite: Your Twinborn Heritage
## Activation:
Resonance description.

## Instinctual Burn
Prerequisite: Misting Snap
Activation:
Burn text 1.

## Instinctual Burn
Prerequisite: Mistborn Snap
Activation:
Burn text 2.

Invested Prerequisite: Mistborn Snap key talent Activation:
Invested description without heading hashes.

## Using Metallic Arts
Chapter 6 overview text.

## Burn Cadmium Activation: Duration: 1 round
You burn cadmium to slow time.

Accelerated Reflexes
Prerequisite: Feruchemy 3+; Sparked Aid talent Activation: V
You accelerate reflexes.

## Pewterarm Weaponcraft
Prerequisite: Heavy Weaponry 1+ or Light Weaponry 1+; Pewter Feruchemy power
Activation:
Weaponcraft description.

<!-- image -->

## Steady Aim
Summary description of steady aim in flowchart without activation.
"""

    gemini_text = """
### Steady Aim
- **Prerequisites:** None
- **Activation:** [2 Actions]

### Iron Will
- **Prerequisites:** Resolve 12
- **Activation:** [Passive]

### Alloyed Resonance
- **Prerequisites:** Your Twinborn Heritage; Invested talent
- **Activation:** [Special Activation]

### Instinctual Burn
- **Prerequisites:** Allomancy 3+; Misting Snap key talent
- **Activation:** [Special Activation]

### Instinctual Burn
- **Prerequisites:** Allomancy 3+; Mistborn Snap key talent
- **Activation:** [Special Activation]

### Invested
- **Prerequisites:** Mistborn Snap key talent
- **Activation:** [Passive]

### Burn Cadmium
- **Prerequisites:** None
- **Activation:** [1 Action]

### Accelerated Reflexes
- **Prerequisites:** Feruchemy 3+; Sparked Aid talent
- **Activation:** [1 Action]

### Pewterarm Weaponcraft
- **Prerequisites:** Heavy Weaponry 1+ or Light Weaponry 1+; Pewter Allomancy power
- **Activation:** [Special Activation]

### Pewterarm Weaponcraft
- **Prerequisites:** Heavy Weaponry 1+ or Light Weaponry 1+; Pewter Feruchemy power
- **Activation:** [Special Activation]
"""

    docling_file.write_text(docling_text, encoding="utf-8")
    gemini_file.write_text(gemini_text, encoding="utf-8")

    merge_chapter(docling_file, gemini_file, out_file)

    merged_text = out_file.read_text(encoding="utf-8")

    # Primary pass verification:
    assert "### Steady Aim" in merged_text
    assert "- **Prerequisites:** None" in merged_text
    assert "- **Activation:** [2 Actions]" in merged_text

    # Fallback pass verification:
    assert "### Iron Will" in merged_text
    assert "- **Prerequisites:** Resolve 12" in merged_text
    assert "- **Activation:** [Passive]" in merged_text

    # Universal inline fix verification:
    assert "gain [2 Actions] for cognitive tests." in merged_text

    # Non-talent header guardrail verification:
    assert "## Mistborn History" in merged_text
    assert "### Mistborn History" not in merged_text
    assert "## Using Metallic Arts" in merged_text
    assert "### Using Metallic Arts" not in merged_text

    # Phantom dash heading prevention verification:
    assert "### Alloyed Resonance" in merged_text
    assert "### -" not in merged_text

    # Occurrence-aware sequential resolution verification:
    assert "- **Prerequisites:** Allomancy 3+; Misting Snap key talent" in merged_text
    assert "- **Prerequisites:** Allomancy 3+; Mistborn Snap key talent" in merged_text

    # Un-headered mangled line verification:
    assert "### Invested" in merged_text
    assert "- **Prerequisites:** Mistborn Snap key talent" in merged_text
    assert "- **Activation:** [Passive]" in merged_text

    # Squashed activation line verification:
    assert "### Burn Cadmium" in merged_text
    assert "- **Activation:** [1 Action]" in merged_text
    assert "### Accelerated Reflexes" in merged_text
    assert "- **Prerequisites:** Feruchemy 3+; Sparked Aid talent" in merged_text

    # Prerequisite word overlap tiebreaker verification:
    assert "- **Prerequisites:** Heavy Weaponry 1+ or Light Weaponry 1+; Pewter Feruchemy power" in merged_text

    # Flowchart protection verification (already processed talents are skipped in fallback):
    assert "## Steady Aim\nSummary description of steady aim in flowchart without activation." in merged_text


def test_patch_file(tmp_path: Path):
    target = tmp_path / "test.md"
    target.write_text("As , you can jump.", encoding="utf-8")

    changed = patch_file(target)
    assert changed is True
    assert "As [1 Action], you can jump." in target.read_text(encoding="utf-8")

    # Re-running on already-patched file returns False (idempotent)
    assert patch_file(target) is False


def test_find_final_outputs(tmp_path: Path):
    # Setup directory with mixed stages:
    # 1. 01-Intro narrative (only DOCLING)
    (tmp_path / "01-Intro - DOCLING.md").write_text("", encoding="utf-8")
    # 2. 04-Paths mechanics (DOCLING, GEMINI, and final MERGED)
    (tmp_path / "04-Paths - DOCLING.md").write_text("", encoding="utf-8")
    (tmp_path / "04-Paths - GEMINI.md").write_text("", encoding="utf-8")
    (tmp_path / "04-Paths - MERGED.md").write_text("", encoding="utf-8")

    final_outputs = find_final_outputs(tmp_path)
    final_names = [f.name for f in final_outputs]

    # Should include 01-Intro (DOCLING is final) and 04-Paths (MERGED is final)
    assert "01-Intro - DOCLING.md" in final_names
    assert "04-Paths - MERGED.md" in final_names
    # Should safely exclude intermediate files
    assert "04-Paths - DOCLING.md" not in final_names
    assert "04-Paths - GEMINI.md" not in final_names
