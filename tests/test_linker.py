"""Tests for OKF Cross-Linker."""

from pathlib import Path

from ttrpg_markdown_pipeline.processors.linker import (
    build_concept_registry,
    compute_relative_link,
    cross_link_vault,
    link_concept_mentions,
)


def test_compute_relative_link():
    src = Path("okf_vault/mistborn/talents/steel_bubble.md")
    tgt = Path("okf_vault/mistborn/rules/actions/disengage.md")
    rel = compute_relative_link(src, tgt)
    assert rel == "../rules/actions/disengage.md"


def test_build_concept_registry(tmp_path: Path):
    vault = tmp_path / "vault"
    t_file = vault / "talents" / "steel_bubble.md"
    t_file.parent.mkdir(parents=True, exist_ok=True)
    t_file.write_text(
        "---\nname: Steel Bubble\ntype: talent\n---\n\nCreates a bubble.\n",
        encoding="utf-8",
    )

    reg = build_concept_registry(vault)
    assert "steel bubble" in reg
    assert reg["steel bubble"].name == "Steel Bubble"
    assert reg["steel bubble"].file_path == t_file.resolve()


def test_link_concept_mentions_avoids_self_link(tmp_path: Path):
    vault = tmp_path / "vault"
    t_file = vault / "talents" / "steel_bubble.md"
    t_file.parent.mkdir(parents=True, exist_ok=True)
    t_file.write_text(
        "---\nname: Steel Bubble\ntype: talent\n---\n\nSteel Bubble protects you.\n",
        encoding="utf-8",
    )

    reg = build_concept_registry(vault)
    # Self-mention should NOT be linked
    res = link_concept_mentions("Steel Bubble protects you.", t_file, reg)
    assert res == "Steel Bubble protects you."


def test_cross_link_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    talents_dir = vault / "talents"
    rules_dir = vault / "rules"
    talents_dir.mkdir(parents=True, exist_ok=True)
    rules_dir.mkdir(parents=True, exist_ok=True)

    action_file = rules_dir / "disengage.md"
    action_file.write_text(
        "---\nname: Disengage\ntype: rule\n---\n\nYou carefully withdraw.\n",
        encoding="utf-8",
    )

    talent_file = talents_dir / "swift_escape.md"
    talent_file.write_text(
        "---\nname: Swift Escape\ntype: talent\n---\n\n"
        "You can Disengage as a free action without opportunity attacks.\n",
        encoding="utf-8",
    )

    modified = cross_link_vault(vault)
    assert modified == 1

    talent_content = talent_file.read_text(encoding="utf-8")
    assert "[Disengage](../rules/disengage.md)" in talent_content


def test_link_concept_mentions_no_double_linking(tmp_path: Path):
    vault = tmp_path / "vault"
    rules_dir = vault / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    disengage_file = rules_dir / "disengage.md"
    disengage_file.write_text("---\nname: Disengage\ntype: rule\n---\n\nWithdraw.", encoding="utf-8")

    heal_file = rules_dir / "heal.md"
    heal_file.write_text("---\nname: Heal\ntype: rule\n---\n\nRestore health.", encoding="utf-8")

    source_file = rules_dir / "item.md"
    source_file.write_text("---\nname: Potion\ntype: item\n---\n\nItem.", encoding="utf-8")

    reg = build_concept_registry(vault)

    # Text that already has a link to Disengage, and code mentions
    text = "You can [Disengage](disengage.md) to escape, or `Disengage` in code, and also heal your party."
    result = link_concept_mentions(text, source_file, reg)

    # [Disengage](disengage.md) should NOT be modified into [[Disengage]...](...)
    assert "[Disengage](disengage.md)" in result
    assert "[[Disengage]" not in result
    assert "`Disengage`" in result
    # "heal" should be linked
    assert "[heal](heal.md)" in result


def test_link_concept_mentions_first_mention_and_idempotent(tmp_path: Path):
    vault = tmp_path / "vault"
    rules_dir = vault / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    cover_file = rules_dir / "cover.md"
    cover_file.write_text("---\nname: Cover\ntype: rule\n---\n\nProtection.", encoding="utf-8")

    brace_file = rules_dir / "brace.md"
    brace_file.write_text(
        "---\nname: Brace\ntype: rule\n---\n\nYou hide behind cover. While behind cover, attacks have disadvantage.",
        encoding="utf-8",
    )

    reg = build_concept_registry(vault)
    text = "You hide behind cover. While behind cover, attacks have disadvantage."
    linked_once = link_concept_mentions(text, brace_file, reg)
    assert linked_once == "You hide behind [cover](cover.md). While behind cover, attacks have disadvantage."

    # Running a second time is idempotent and does not link the second occurrence
    linked_twice = link_concept_mentions(linked_once, brace_file, reg)
    assert linked_twice == linked_once
