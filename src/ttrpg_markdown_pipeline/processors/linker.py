"""OKF Cross-Linker: Generates explicit markdown links across concepts in an OKF vault.

Builds a registry of all concept names to relative file paths, crawls every markdown
file's body text, and links mentions of known concepts to their definition files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

import yaml


class RegisteredConcept(NamedTuple):
    name: str
    file_path: Path
    slug: str


def build_concept_registry(vault_dir: Path) -> dict[str, RegisteredConcept]:
    """Scans vault_dir for .md files and indexes concepts by name and lowercase name."""
    registry: dict[str, RegisteredConcept] = {}

    for md_file in vault_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue

        if not content.startswith("---\n"):
            continue

        parts = content.split("---\n", 2)
        if len(parts) < 3:
            continue

        try:
            frontmatter = yaml.safe_load(parts[1])
            if isinstance(frontmatter, dict) and "name" in frontmatter:
                raw_name = str(frontmatter["name"]).strip()
                if raw_name:
                    reg = RegisteredConcept(
                        name=raw_name,
                        file_path=md_file.resolve(),
                        slug=md_file.stem,
                    )
                    registry[raw_name.lower()] = reg
        except yaml.YAMLError:
            continue

    return registry


def compute_relative_link(source_file: Path, target_file: Path) -> str:
    """Calculates a forward-slash relative markdown link between two files."""
    rel = os.path.relpath(target_file, source_file.parent)
    return rel.replace("\\", "/")


def link_concept_mentions(
    body_text: str,
    source_file: Path,
    registry: dict[str, RegisteredConcept],
) -> str:
    """Replaces mentions of registered concepts in body_text with markdown links."""
    current_canonical = None
    # Avoid self-linking
    for reg in registry.values():
        if reg.file_path == source_file.resolve():
            current_canonical = reg.name.lower()
            break

    # Sort registry keys by descending length so multi-word concepts match before single words
    sorted_names = sorted(
        (name for name in registry if name != current_canonical and len(name) > 2),
        key=len,
        reverse=True,
    )

    if not sorted_names:
        return body_text

    tokens: dict[str, str] = {}
    counter = 0

    def protect_match(m: re.Match[str]) -> str:
        nonlocal counter
        ph = f"\x00TOKEN_{counter}\x00"
        tokens[ph] = m.group(0)
        counter += 1
        return ph

    # Protect code blocks, inline code, and existing markdown links
    protect_pattern = re.compile(r"```[\s\S]*?```|`[^`\n]+`|\[[^\]]+\]\([^\)]+\)")
    linked_text = protect_pattern.sub(protect_match, body_text)

    for name in sorted_names:
        target_concept = registry[name]
        rel_link = compute_relative_link(source_file, target_concept.file_path)

        pattern = re.compile(rf"\b({re.escape(name)})\b", re.IGNORECASE)

        def replace_mention(m: re.Match[str], link: str = rel_link) -> str:
            nonlocal counter
            ph = f"\x00TOKEN_{counter}\x00"
            tokens[ph] = f"[{m.group(1)}]({link})"
            counter += 1
            return ph

        linked_text = pattern.sub(replace_mention, linked_text)

    for ph, original_or_link in tokens.items():
        linked_text = linked_text.replace(ph, original_or_link)

    return linked_text


def cross_link_vault(vault_dir: Path) -> int:
    """Crawls vault_dir, cross-links all concept mentions in body_text, and returns modified count."""
    registry = build_concept_registry(vault_dir)
    modified_count = 0

    for md_file in vault_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            continue

        parts = content.split("---\n", 2)
        if len(parts) < 3:
            continue

        frontmatter = parts[1]
        body = parts[2]

        new_body = link_concept_mentions(body, md_file, registry)
        if new_body != body:
            md_file.write_text(f"---\n{frontmatter}---\n{new_body}", encoding="utf-8")
            modified_count += 1

    return modified_count
