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

from ttrpg_markdown_pipeline.models import (
    OKFAdversary,
    OKFArmor,
    OKFConcept,
    OKFItem,
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

    # Collapse 3+ consecutive newlines
    cleaned = re.sub(r"(\r?\n\s*){3,}", "\n\n", cleaned)

    return cleaned.strip()


def split_mechanics_and_examples(text: str) -> tuple[str, str | None]:
    """Splits a body of rules text into pure mechanical rules and play examples / dialogue."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs:
        return "", None

    mechanics_paras: list[str] = []
    example_paras: list[str] = []

    speaker_pattern = re.compile(r"^(?:[A-Z][a-zA-Z\s]{1,15}|GM|DM):\s+")
    example_heading_pattern = re.compile(
        r"^(?:#{1,4}\s*)?(?:\*\*|\*)?Example(?:\s+(?:Play|of\s+Play))?(?:\*\*|\*)?:?",
        re.IGNORECASE,
    )
    heading_pattern = re.compile(r"^#{1,4}\s+")

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
        elif speaker_pattern.match(lines[0]):
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

    raw_body = ""
    if docling_body and docling_body.strip():
        # Prefer Docling verbatim layout text if matched, repaired with inline glyphs
        raw_body = clean_extraction_artifacts(apply_inline_repairs(docling_body))
    elif "body_text" in merged_dict and merged_dict["body_text"]:
        # Fallback to Gemini body text repaired with inline glyphs
        raw_body = clean_extraction_artifacts(apply_inline_repairs(str(merged_dict["body_text"])))

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
    return OKFRule(**merged_dict)


def parse_gemini_json_payload(gemini_raw_text: str) -> list[dict[str, Any]]:
    """Extracts a JSON list of concept objects from Gemini output, handling code fences or multiple chunks."""
    # Look for code fenced json first
    json_blocks = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", gemini_raw_text, re.DOTALL)
    combined_items: list[dict[str, Any]] = []

    if json_blocks:
        for block in json_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, list):
                    combined_items.extend(data)
            except json.JSONDecodeError:
                continue

    if combined_items:
        return combined_items

    # If no valid code fence found, scan for raw JSON lists in text
    raw_lists = re.findall(r"\[\s*\{.*?\}\s*\]", gemini_raw_text, re.DOTALL)
    for raw in raw_lists:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                combined_items.extend(data)
        except json.JSONDecodeError:
            continue

    return combined_items


def shred_chapter(
    docling_md_path: Path,
    gemini_output_path: Path,
    vault_dir: Path,
    default_sourcebook: str = "Cosmere RPG",
) -> list[Path]:
    """Shreds a single chapter's Docling & Gemini output into atomic OKF Markdown files in vault_dir."""
    docling_text = clean_extraction_artifacts(docling_md_path.read_text(encoding="utf-8"))
    gemini_text = gemini_output_path.read_text(encoding="utf-8")

    docling_sections = split_docling_by_headers(docling_text)
    concepts_raw = parse_gemini_json_payload(gemini_text)

    saved_files: list[Path] = []

    for item in concepts_raw:
        if not isinstance(item, dict) or "name" not in item:
            continue

        if "sourcebook" not in item or not item["sourcebook"]:
            item["sourcebook"] = default_sourcebook

        name = str(item["name"])
        slug = sanitize_slug(name)

        # Look up matching Docling text section
        matched_body = docling_sections.get(slug)
        if not matched_body:
            # Try fuzzy partial key match
            for k, sec in docling_sections.items():
                if k in slug or slug in k:
                    matched_body = sec
                    break

        concept = instantiate_okf_concept(item, docling_body=matched_body)

        sourcebook_slug = sanitize_slug(concept.sourcebook)
        type_folder = f"{concept.type}s"
        target_dir = vault_dir / sourcebook_slug / type_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / f"{slug}.md"
        file_path.write_text(concept.to_markdown(), encoding="utf-8")
        saved_files.append(file_path)

    return saved_files
