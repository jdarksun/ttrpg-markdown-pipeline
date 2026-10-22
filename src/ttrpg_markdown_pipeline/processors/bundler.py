"""NotebookLM Bundler: Compiles atomic OKF Markdown files into consolidated category bundles.

Crawls the /okf_vault/ by sourcebook and type (e.g., all Mistborn Talents),
and concatenates all atomic concept files into a single bundle with preserved YAML frontmatter.
"""

from __future__ import annotations

from pathlib import Path


def sanitize_bundle_name(sourcebook: str, concept_type: str) -> str:
    """Creates a clean bundle filename like 'Mistborn_All_Talents.md'."""
    src_title = "_".join(word.capitalize() for word in sourcebook.replace("-", " ").split("_"))
    type_title = "_".join(word.capitalize() for word in concept_type.replace("-", " ").split("_"))
    return f"{src_title}_All_{type_title}.md"


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
            bundled_sections.append(content)

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
