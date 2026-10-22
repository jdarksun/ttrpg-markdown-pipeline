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
                if not body_raw.startswith("### Mechanics"):
                    blocks.append(f"### Mechanics\n\n{body_raw}")
                else:
                    blocks.append(body_raw)

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

    md_files = sorted(type_dir.glob("*.md"))
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

    return generated_bundles
