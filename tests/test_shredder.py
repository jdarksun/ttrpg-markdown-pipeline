"""Tests for OKF Shredder."""

import json
from pathlib import Path

import yaml

from ttrpg_markdown_pipeline.processors.shredder import (
    parse_gemini_json_payload,
    sanitize_slug,
    shred_chapter,
    split_docling_by_headers,
)


def test_sanitize_slug():
    assert sanitize_slug("Steel Bubble") == "steel_bubble"
    assert sanitize_slug("Pewterarm Weaponcraft (Era 2)") == "pewterarm_weaponcraft_era_2"
    assert sanitize_slug("Dueling Cane: Noble's Guard") == "dueling_cane_nobles_guard"


def test_split_docling_by_headers():
    docling_md = (
        "## Steel Bubble\n\n"
        "You create an invisible bubble around yourself.\n\n"
        "### Iron Stance\n\n"
        "You anchor yourself to metal in the ground.\n"
    )

    sections = split_docling_by_headers(docling_md)
    assert "steel_bubble" in sections
    assert "iron_stance" in sections
    assert "You create an invisible bubble around yourself." in sections["steel_bubble"]
    assert "You anchor yourself to metal in the ground." in sections["iron_stance"]


def test_parse_gemini_json_payload_fenced():
    raw_response = (
        "Here are the extracted concepts:\n\n"
        "```json\n"
        "[\n"
        '  {"name": "Steel Bubble", "type": "talent", "sourcebook": "Mistborn", '
        '"category": "Steel", "activation": "2 actions"}\n'
        "]\n"
        "```\n"
        "Enjoy!"
    )
    items = parse_gemini_json_payload(raw_response)
    assert len(items) == 1
    assert items[0]["name"] == "Steel Bubble"
    assert items[0]["activation"] == "2 actions"


def test_shred_chapter(tmp_path: Path):
    docling_file = tmp_path / "04-Chapter - DOCLING.md"
    docling_file.write_text(
        "## Steel Bubble\n\n"
        "You can enter another stance you know as ▷.\n\n"
        "## Dueling Cane\n\n"
        "A swift concealed weapon.\n",
        encoding="utf-8",
    )

    gemini_file = tmp_path / "04-Chapter - GEMINI.md"
    gemini_data = [
        {
            "schema_version": "1.0.0",
            "sourcebook": "Mistborn World Guide",
            "type": "talent",
            "name": "Steel Bubble",
            "category": "Steel Allomancy",
            "prerequisites": "Steel 2+",
            "activation": "2 actions",
        },
        {
            "schema_version": "1.0.0",
            "sourcebook": "Mistborn World Guide",
            "type": "weapon",
            "name": "Dueling Cane",
            "category": "Light Weaponry",
            "damage": "1d6 physical",
            "traits": ["Discreet"],
        },
    ]
    gemini_file.write_text(f"```json\n{json.dumps(gemini_data)}\n```", encoding="utf-8")

    vault_dir = tmp_path / "okf_vault"
    saved = shred_chapter(docling_file, gemini_file, vault_dir)

    assert len(saved) == 2

    # Check talent file
    talent_file = vault_dir / "mistborn_world_guide" / "talents" / "steel_bubble.md"
    assert talent_file.exists()
    content = talent_file.read_text(encoding="utf-8")
    assert "activation: '[2 Actions]'" in content or 'activation: "[2 Actions]"' in content or "[2 Actions]" in content
    # Check that Docling text was repaired by inline fixes (▷ -> [Free Action])
    assert "[Free Action]" in content

    # Check weapon file
    weapon_file = vault_dir / "mistborn_world_guide" / "weapons" / "dueling_cane.md"
    assert weapon_file.exists()
    w_content = weapon_file.read_text(encoding="utf-8")
    parts = w_content.split("---\n")
    data = yaml.safe_load(parts[1])
    assert data["type"] == "weapon"
    assert data["damage"] == "1d6 physical"
