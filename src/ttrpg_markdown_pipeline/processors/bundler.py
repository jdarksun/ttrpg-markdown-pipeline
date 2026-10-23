"""NotebookLM Bundler: Compiles atomic OKF Markdown files into consolidated category bundles.

Crawls the /okf_vault/ by sourcebook and type (e.g., all Mistborn Talents),
and concatenates all atomic concept files into a single bundle with preserved YAML frontmatter.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def sanitize_bundle_name(sourcebook: str, concept_type: str) -> str:
    """Creates a clean bundle filename like 'Mistborn_All_Talents.md'."""
    src_title = "_".join(word.capitalize() for word in sourcebook.replace("-", " ").split("_"))
    type_title = "_".join(word.capitalize() for word in concept_type.replace("-", " ").split("_"))
    return f"{src_title}_All_{type_title}.md"


def format_concept_for_bundle(atomic_markdown: str) -> str:
    """Formats an atomic OKF Markdown document for inclusion in a bundle.

    Converts mid-document YAML frontmatter to a fenced ```yaml code block
    preceded by an ATX heading '## <Name>' to prevent CommonMark Setext heading collisions.
    """
    clean_text = atomic_markdown.strip()
    if not clean_text:
        return ""

    if clean_text.startswith("---"):
        parts = clean_text.split("---", 2)
        if len(parts) >= 3:
            yaml_raw = parts[1].strip()
            body_raw = parts[2].strip()

            concept_name = "Concept"
            try:
                meta = yaml.safe_load(yaml_raw)
                if isinstance(meta, dict) and meta.get("name"):
                    concept_name = str(meta["name"])
            except Exception:
                name_match = re.search(r"^name:\s*['\"]?(.*?)['\"]?$", yaml_raw, re.MULTILINE)
                if name_match:
                    concept_name = name_match.group(1).strip()

            blocks = [f"## {concept_name}", f"```yaml\n{yaml_raw}\n```"]
            if body_raw:
                # Replace relative .md file links with clean bold callouts for monolithic bundles
                clean_body = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\.md\)", r"**\1**", body_raw)
                if not clean_body.startswith("### "):
                    blocks.append(f"### Mechanics\n\n{clean_body}")
                else:
                    blocks.append(clean_body)

            return "\n\n".join(blocks)

    return clean_text


def bundle_category(
    vault_dir: Path,
    sourcebook_slug: str,
    concept_type_folder: str,
    output_dir: Path,
) -> Path | None:
    """Bundles all atomic concept files in a given sourcebook/type folder into a single file."""
    type_dir = vault_dir / sourcebook_slug / concept_type_folder
    if not type_dir.exists() or not type_dir.is_dir():
        return None

    md_files = sorted(type_dir.glob("*.md"), key=natural_sort_key)
    if not md_files:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_filename = sanitize_bundle_name(sourcebook_slug, concept_type_folder)
    out_file = output_dir / bundle_filename

    bundled_sections: list[str] = []

    for file_path in md_files:
        content = file_path.read_text(encoding="utf-8").strip()
        if content:
            bundled_sections.append(format_concept_for_bundle(content))

    # Concatenate preserving YAML frontmatter blocks separated by horizontal rules
    out_file.write_text("\n\n---\n\n".join(bundled_sections) + "\n", encoding="utf-8")
    return out_file


def natural_sort_key(path: Path) -> list[int | str]:
    """Provides natural alphanumeric sorting key (e.g. 'a2' sorts before 'a10')."""
    parts = re.split(r"(\d+)", path.stem.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def bundle_campaign(vault_dir: Path, output_dir: Path) -> list[Path]:
    """Generates an all-in-one interactive GM Campaign Guide for sourcebooks with adventure nodes."""
    generated_campaigns: list[Path] = []
    if not vault_dir.exists():
        return generated_campaigns

    for sb_dir in sorted(vault_dir.iterdir()):
        if not sb_dir.is_dir():
            continue

        adv_dir = sb_dir / "adventure_nodes"
        if not adv_dir.exists() or not adv_dir.is_dir():
            continue

        node_files = sorted(adv_dir.glob("*.md"), key=natural_sort_key)
        if not node_files:
            continue

        sourcebook_slug = sb_dir.name
        src_title = " ".join(word.capitalize() for word in sourcebook_slug.replace("-", " ").split("_"))

        output_dir.mkdir(parents=True, exist_ok=True)
        name_parts = [word.capitalize() for word in sourcebook_slug.replace("-", " ").split("_")]
        campaign_filename = f"{'_'.join(name_parts)}_GM_Campaign_Guide.md"
        campaign_file = output_dir / campaign_filename

        sections: list[str] = [
            f"# {src_title} - Interactive GM Campaign Guide\n\n"
            "> ## GM / Solo Referee System Instructions\n"
            "> You are the Game Master / Referee facilitating this interactive adventure module.\n"
            ">\n"
            "> ### Operational Protocol:\n"
            "> 1. **Step-by-Step Traversal:** Present only ONE scene or decision node (`node_id`) at a time. Never disclose, summarize, or spoil upcoming branches, future nodes, or secret DC results.\n"  # noqa: E501
            "> 2. **Boxed Text & Atmosphere:** Read `### Read-Aloud` text verbatim with immersive narration and vivid tone.\n"  # noqa: E501
            "> 3. **Skill Checks & Challenges:** When a scene calls for a test from `### Skill Checks`, prompt the player to make the check, await their roll result, and resolve based on the specified DC and success/failure outcome.\n"  # noqa: E501
            "> 4. **State Machine & Mutation Tracking:** Keep strict track of player/party status changes specified in `state_mutations` (e.g. Attribute increases, Skill ranks, Resource pools, Ideals, and Conditions like `Exhausted` or `Alert`). Confirm state changes to the player when applied.\n"  # noqa: E501
            "> 5. **Choices & Navigation:** Present the options listed under `### Choices & Branches`. Prompt the player for their decision. Do not advance to the target node until the player chooses or rolls.\n"  # noqa: E501
            "> 6. **Combat & Encounters:** When an encounter node references an adversary, refer to the **Module Compendium: Adversaries** section at the bottom of this document for stats, actions, reactions, opportunities, and complications."  # noqa: E501
        ]

        # Add all adventure nodes in play order
        for n_file in node_files:
            content = n_file.read_text(encoding="utf-8").strip()
            if content:
                sections.append(format_concept_for_bundle(content))

        # Add sibling categories as inline compendiums
        compendium_order = [
            "adversaries",
            "weapons",
            "armors",
            "items",
            "talents",
            "rules",
            "lore",
            "factions",
            "locations",
        ]
        for cat in compendium_order:
            cat_dir = sb_dir / cat
            if cat_dir.exists() and cat_dir.is_dir():
                cat_files = sorted(cat_dir.glob("*.md"))
                if cat_files:
                    cat_title = cat.capitalize()
                    sections.append(f"# Module Compendium: {cat_title}")
                    for c_file in cat_files:
                        c_content = c_file.read_text(encoding="utf-8").strip()
                        if c_content:
                            sections.append(format_concept_for_bundle(c_content))

        campaign_file.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
        generated_campaigns.append(campaign_file)

    return generated_campaigns


def bundle_vault(vault_dir: Path, output_dir: Path) -> list[Path]:
    """Crawls all sourcebooks and concept types in vault_dir and generates consolidated bundles."""
    generated_bundles: list[Path] = []
    if not vault_dir.exists():
        return generated_bundles

    for sb_dir in sorted(vault_dir.iterdir()):
        if not sb_dir.is_dir():
            continue
        sourcebook_slug = sb_dir.name

        for type_dir in sorted(sb_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            type_folder = type_dir.name

            bundle_file = bundle_category(vault_dir, sourcebook_slug, type_folder, output_dir)
            if bundle_file:
                generated_bundles.append(bundle_file)

    # Generate GM Campaign Guides for any modules with adventure nodes
    campaign_guides = bundle_campaign(vault_dir, output_dir)
    generated_bundles.extend(campaign_guides)

    return generated_bundles
