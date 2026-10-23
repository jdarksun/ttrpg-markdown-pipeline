"""OKF Shredder: Combines Docling layout precision with Gemini OKF JSON metadata.

Splits Docling markdown into chunks by headings, matches them with structured OKF
JSON concepts returned by Gemini, applies universal inline symbol repairs, and emits
atomic concept markdown files into a structured OKF vault.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import yaml

from ttrpg_markdown_pipeline.models import (
    OKFAdventureNode,
    OKFAdversary,
    OKFArmor,
    OKFConcept,
    OKFItem,
    OKFLoreEntry,
    OKFRule,
    OKFTalent,
    OKFWeapon,
)
from ttrpg_markdown_pipeline.rules.cosmere import UNIVERSAL_INLINE_FIXES


def sanitize_slug(name: str) -> str:
    """Creates a filesystem-safe normalized slug from a concept name."""
    cleaned = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[-\s]+", "_", cleaned).strip("-_")


def split_docling_by_headers(docling_text: str) -> dict[str, str]:
    """Splits Docling markdown by ## or ### headings into {normalized_name: section_text}."""
    # Matches ## or ### Heading lines
    sections: dict[str, str] = {}
    pattern = re.compile(r"^(#{2,3})\s+([^\n]+)", re.MULTILINE)

    matches = list(pattern.finditer(docling_text))
    if not matches:
        return sections

    for i, m in enumerate(matches):
        raw_title = m.group(2).strip()
        # Clean tags like Era 2, numerals, parentheticals
        clean_title = re.sub(r"\s*\([^)]*\)", "", raw_title).strip()
        norm_key = sanitize_slug(clean_title)

        start_pos = m.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(docling_text)
        section_body = docling_text[start_pos:end_pos].strip()

        sections[norm_key] = section_body

    return sections


def apply_inline_repairs(text: str) -> str:
    """Applies universal regex fixes to repair dropped action economy and plot symbols."""
    patched = text
    for pattern, replacement in UNIVERSAL_INLINE_FIXES.items():
        patched = re.sub(pattern, replacement, patched)
    return patched


def clean_extraction_artifacts(text: str) -> str:
    """Cleans Docling extraction artifacts, publisher watermarks, stray OCR glyphs, and unescapes HTML."""
    if not text:
        return ""

    # Unescape HTML entities (e.g. &amp; -> &, &lt; -> <)
    cleaned = html.unescape(text)

    # Strip Docling image comments
    cleaned = re.sub(r"^[ \t]*<!--\s*image.*-->[ \t]*$\n?", "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # Strip publisher / DriveThruRPG watermarks
    cleaned = re.sub(
        r"Downloaded by [^\n\r]*(?:\r?\n[^\n\r]*)?Unauthorized distribution prohibited\.?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^.*Downloaded by .*$\n?", "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    cleaned = re.sub(
        r"^.*Unauthorized distribution prohibited\.?.*$\n?",
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Strip standalone bullet and optional page number footers (e.g. '● 48', '●\n\n48', '• 12', or standalone '●')
    cleaned = re.sub(
        r"^[ \t]*[●•](?:[ \t]+|\r?\n[ \t]*)*(?:\d+)?[ \t]*$\n?",
        "",
        cleaned,
        flags=re.MULTILINE,
    )

    # Strip stray single-letter OCR noise lines (e.g. 'M', 'V')
    cleaned = re.sub(r"^[ \t]*[MV][ \t]*$\n?", "", cleaned, flags=re.MULTILINE)

    # Strip standalone page number lines (e.g. '44', '28')
    cleaned = re.sub(r"^[ \t]*\d{1,4}[ \t]*$\n?", "", cleaned, flags=re.MULTILINE)

    # Collapse 3+ consecutive newlines
    cleaned = re.sub(r"(\r?\n\s*){3,}", "\n\n", cleaned)

    return cleaned.strip()


STAT_BLOCK_LABELS = {
    "physical",
    "cognitive",
    "spiritual",
    "deflect",
    "movement",
    "senses",
    "skills",
    "physical skills",
    "cognitive skills",
    "spiritual skills",
    "languages",
    "health",
    "focus",
    "investiture",
    "traits",
    "expert traits",
    "weapon traits",
    "armor traits",
    "prerequisite",
    "prerequisites",
    "activation",
    "trigger",
    "target",
    "targets",
    "duration",
    "range",
    "damage",
    "cost",
    "price",
    "weight",
    "tier",
    "role",
    "size",
    "speed",
    "strength",
    "intellect",
    "willpower",
    "awareness",
    "presence",
    "actions",
    "reactions",
    "free actions",
    "features",
    "tactics",
    "immunities",
    "resistances",
    "vulnerabilities",
    "condition",
    "conditions",
    "effect",
    "effects",
    "strike",
    "graze",
    "hit",
    "miss",
    "critical",
    "success",
    "failure",
    "opportunity",
    "opportunities",
    "complication",
    "complications",
    "note",
    "warning",
    "tip",
    "gm tip",
    "rules tip",
    "on your character sheet",
}


def split_mechanics_and_examples(text: str) -> tuple[str, str | None]:
    """Splits a body of rules text into pure mechanical rules and play examples / dialogue."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs:
        return "", None

    mechanics_paras: list[str] = []
    example_paras: list[str] = []

    speaker_pattern = re.compile(r"^([A-Z][a-zA-Z\s]{1,22}|GM|DM):\s+")
    example_heading_pattern = re.compile(
        r"^(?:#{1,4}\s*)?(?:\*\*|\*)?Example(?:\s+(?:Play|of\s+Play))?(?:\*\*|\*)?:?",
        re.IGNORECASE,
    )
    heading_pattern = re.compile(r"^#{1,4}\s+")

    def _is_dialogue_speaker(line: str) -> bool:
        m = speaker_pattern.match(line)
        if not m:
            return False
        label = m.group(1).strip().lower()
        return label not in STAT_BLOCK_LABELS

    in_example_block = False

    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines() if line.strip()]
        if not lines:
            continue

        if example_heading_pattern.match(lines[0]):
            in_example_block = True
            example_paras.append(para)
        elif in_example_block:
            if heading_pattern.match(lines[0]) and not example_heading_pattern.match(lines[0]):
                in_example_block = False
                mechanics_paras.append(para)
            else:
                example_paras.append(para)
        elif _is_dialogue_speaker(lines[0]):
            example_paras.append(para)
        else:
            mechanics_paras.append(para)

    if not mechanics_paras:
        return text.strip(), None

    mechanics_text = "\n\n".join(mechanics_paras).strip()
    example_text = "\n\n".join(example_paras).strip() if example_paras else None
    return mechanics_text, example_text


def instantiate_okf_concept(item_dict: dict[str, Any], docling_body: str | None = None) -> OKFConcept:
    """Instantiates the specialized OKF Pydantic model according to 'type'."""
    c_type = str(item_dict.get("type", "rule")).lower()
    merged_dict = dict(item_dict)

    if "category" not in merged_dict or not merged_dict["category"]:
        merged_dict["category"] = "General"

    raw_body = ""
    if "body_text" in merged_dict and str(merged_dict["body_text"]).strip():
        # Prefer Gemini Vision body text (preserves PUA action icons, clean tables, and column boundaries)
        raw_body = clean_extraction_artifacts(apply_inline_repairs(str(merged_dict["body_text"])))
    elif docling_body and docling_body.strip():
        # Fallback to Docling layout text if Gemini omitted body_text
        raw_body = clean_extraction_artifacts(apply_inline_repairs(docling_body))

    if raw_body:
        mech_text, ex_text = split_mechanics_and_examples(raw_body)
        merged_dict["body_text"] = mech_text
        if ex_text and not merged_dict.get("example_text"):
            merged_dict["example_text"] = ex_text

    if "example_text" in merged_dict and merged_dict["example_text"]:
        merged_dict["example_text"] = clean_extraction_artifacts(str(merged_dict["example_text"]))

    if c_type == "talent":
        return OKFTalent(**merged_dict)
    if c_type == "weapon":
        return OKFWeapon(**merged_dict)
    if c_type == "armor":
        return OKFArmor(**merged_dict)
    if c_type == "item":
        return OKFItem(**merged_dict)
    if c_type == "adversary":
        return OKFAdversary(**merged_dict)
    if c_type in ("lore", "faction", "location"):
        return OKFLoreEntry(**merged_dict)
    if c_type == "adventure_node":
        return OKFAdventureNode(**merged_dict)
    return OKFRule(**merged_dict)


def _salvage_truncated_json_array(chunk_text: str) -> list[dict[str, Any]]:
    """Attempts to recover complete JSON objects from a truncated JSON array block."""
    start = chunk_text.find("[")
    if start == -1:
        return []
    candidate = chunk_text[start:]
    # Walk backwards to find the last closing brace '}' that completes a valid JSON array when ']' is appended
    pos = len(candidate)
    while True:
        brace_idx = candidate.rfind("}", 0, pos)
        if brace_idx == -1:
            break
        attempt = candidate[: brace_idx + 1] + "\n]"
        try:
            data = json.loads(attempt)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
        pos = brace_idx
    return []


def _parse_single_chunk_json(chunk_text: str) -> list[dict[str, Any]]:
    """Extracts a JSON list of concept objects from a single Gemini chunk."""
    items: list[dict[str, Any]] = []

    json_blocks = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", chunk_text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, list):
                items.extend(d for d in data if isinstance(d, dict))
        except json.JSONDecodeError:
            items.extend(_salvage_truncated_json_array(block))

    if items:
        return items

    raw_lists = re.findall(r"\[\s*\{.*?\}\s*\]", chunk_text, re.DOTALL)
    for raw in raw_lists:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                items.extend(d for d in data if isinstance(d, dict))
        except json.JSONDecodeError:
            continue

    if items:
        return items

    return _salvage_truncated_json_array(chunk_text)


def parse_gemini_json_payload(gemini_raw_text: str) -> list[dict[str, Any]]:
    """Extracts a JSON list of concept objects from Gemini output, handling code fences or multiple chunks."""
    if "<!-- OKF_CHUNK_BOUNDARY -->" in gemini_raw_text:
        chunks = gemini_raw_text.split("<!-- OKF_CHUNK_BOUNDARY -->")
    else:
        chunks = re.split(r"(?:^|\r?\n)[ \t]*---[ \t]*(?:\r?\n|$)", gemini_raw_text)
    combined_items: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.strip():
            combined_items.extend(_parse_single_chunk_json(chunk))
    return combined_items


TYPE_FOLDER_MAPPING = {
    "adversary": "adversaries",
    "lore": "lore",
    "faction": "factions",
    "location": "locations",
    "adventure_node": "adventure_nodes",
}


def consolidate_concepts(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicates and merges concept dictionaries sharing (type, slug).

    Merges non-null metadata and retains the richest/longest body_text and example_text.
    Preserves original insertion order.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for item in concepts:
        if not isinstance(item, dict) or not item.get("name"):
            continue

        c_type = str(item.get("type", "rule")).lower()
        if c_type == "adventure_node" and item.get("node_id"):
            slug = sanitize_slug(str(item["node_id"]))
        else:
            slug = sanitize_slug(str(item["name"]))
        key = (c_type, slug)

        if key not in grouped:
            grouped[key] = dict(item)
            continue

        existing = grouped[key]
        for field, val in item.items():
            if val is None or val == "":
                continue

            if field == "body_text":
                if len(str(val).strip()) > len(str(existing.get("body_text", "")).strip()):
                    existing["body_text"] = val
            elif field == "example_text":
                if not existing.get("example_text") or len(str(val).strip()) > len(
                    str(existing.get("example_text", "")).strip()
                ):
                    existing["example_text"] = val
            elif field == "read_aloud":
                if len(str(val).strip()) > len(str(existing.get("read_aloud", "")).strip()):
                    existing["read_aloud"] = val
            elif field in (
                "traits",
                "key_themes",
                "adventure_hooks",
                "skill_checks",
                "state_mutations",
                "choices",
                "journal_prompts",
            ) and isinstance(val, list):
                existing_list = existing.get(field) or []
                if isinstance(existing_list, list):
                    merged_list = list(existing_list)
                    for elem in val:
                        if elem not in merged_list:
                            merged_list.append(elem)
                    existing[field] = merged_list
                else:
                    existing[field] = val
            else:
                if existing.get(field) is None or existing.get(field) == "":
                    existing[field] = val

    return list(grouped.values())


def shred_chapter(
    docling_md_path: Path,
    gemini_output_path: Path,
    vault_dir: Path,
    default_sourcebook: str | None = None,
) -> list[Path]:
    """Shreds a single chapter's Docling & Gemini output into atomic OKF Markdown files in vault_dir."""
    docling_text = clean_extraction_artifacts(docling_md_path.read_text(encoding="utf-8"))
    gemini_text = gemini_output_path.read_text(encoding="utf-8")

    docling_sections = split_docling_by_headers(docling_text)
    concepts_raw = parse_gemini_json_payload(gemini_text)
    concepts_consolidated = consolidate_concepts(concepts_raw)

    saved_files: list[Path] = []

    for item in concepts_consolidated:
        if not isinstance(item, dict) or "name" not in item:
            continue

        # Enforce canonical sourcebook if provided; otherwise fallback to existing or Cosmere RPG
        if default_sourcebook:
            item["sourcebook"] = default_sourcebook
        elif "sourcebook" not in item or not item["sourcebook"]:
            item["sourcebook"] = "Cosmere RPG"

        name = str(item["name"])
        c_type = str(item.get("type", "rule")).lower()
        if c_type == "adventure_node" and item.get("node_id"):
            node_id_slug = sanitize_slug(str(item["node_id"]))
            name_slug = sanitize_slug(name)
            slug = f"{node_id_slug}_{name_slug}" if name_slug != node_id_slug else node_id_slug
        else:
            slug = sanitize_slug(name)

        # Look up matching Docling text section
        matched_body = docling_sections.get(slug)
        if not matched_body:
            # Normalized match
            slug_clean = slug.replace("_", "")
            for k, sec in docling_sections.items():
                if k.replace("_", "") == slug_clean:
                    matched_body = sec
                    break

        if not matched_body:
            # Prefix match only for multi-word or long slugs (preventing false matches on short words)
            for k, sec in docling_sections.items():
                if (
                    (len(k) >= 8 or "_" in k)
                    and (len(slug) >= 8 or "_" in slug)
                    and (slug.startswith(f"{k}_") or k.startswith(f"{slug}_"))
                ):
                    matched_body = sec
                    break

        sourcebook_slug = sanitize_slug(str(item.get("sourcebook") or default_sourcebook))
        type_folder = TYPE_FOLDER_MAPPING.get(c_type, f"{c_type}s")
        target_dir = vault_dir / sourcebook_slug / type_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / f"{slug}.md"

        # If file already exists in vault, merge existing data with new concept
        if file_path.exists():
            try:
                existing_raw = file_path.read_text(encoding="utf-8")
                parts = existing_raw.split("---\n")
                if len(parts) >= 3:
                    existing_meta = yaml.safe_load(parts[1]) or {}
                    existing_body = parts[2].strip()
                    existing_item = dict(existing_meta)
                    existing_item["body_text"] = existing_body
                    merged_items = consolidate_concepts([existing_item, item])
                    item = merged_items[0]
            except Exception:
                pass

        concept = instantiate_okf_concept(item, docling_body=matched_body)
        file_path.write_text(concept.to_markdown(), encoding="utf-8")
        saved_files.append(file_path)

    return saved_files
