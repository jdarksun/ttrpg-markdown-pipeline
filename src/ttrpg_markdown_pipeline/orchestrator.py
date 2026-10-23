"""Cosmere / TTRPG Pipeline Orchestrator with Open Knowledge Format (OKF) Architecture."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from docling.document_converter import DocumentConverter

from ttrpg_markdown_pipeline.common import DOCLING_TAG, GEMINI_TAG, clean_path, tagged_md_path
from ttrpg_markdown_pipeline.extractors.api import extract_pdf_async
from ttrpg_markdown_pipeline.extractors.docling import convert_pdf
from ttrpg_markdown_pipeline.extractors.gemini import get_run_report, reset_run_report
from ttrpg_markdown_pipeline.processors.bundler import bundle_vault
from ttrpg_markdown_pipeline.processors.linker import cross_link_vault
from ttrpg_markdown_pipeline.processors.patch import patch_file
from ttrpg_markdown_pipeline.processors.shredder import shred_chapter
from ttrpg_markdown_pipeline.rules.cosmere import (
    ADVENTURE_KEYWORDS,
    ADVENTURE_PROMPT,
    DEFAULT_PROMPT,
    LORE_KEYWORDS,
    LORE_PROMPT,
    MECHANICS_KEYWORDS,
    is_substantive_chapter,
)


@dataclass
class Chapter:
    path: Path
    title: str
    mechanics: bool
    mode: str = "mechanics"


def sanitize_filename(name: str) -> str:
    """Removes invalid filename characters, control characters, and collapses whitespace."""
    cleaned = re.sub(r"[\r\n\t]+", " ", name)
    cleaned = re.sub(r'[\\/*?:"<>|]', "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def split_pdf_by_chapters(
    pdf_path: Path,
    output_dir: Path,
    *,
    all_mechanics: bool = False,
    include_lore: bool = False,
    adventure_mode: bool = False,
) -> list[Chapter]:
    """Reads the TOC, splits the PDF into chapter files, and returns their metadata.

    Raises ValueError if the PDF has no usable Table of Contents.
    """
    print(f"\n[Orchestrator] Reading Table of Contents from {pdf_path.name}...")
    doc = pymupdf.open(pdf_path)
    try:
        toc = doc.get_toc()

        if not toc:
            raise ValueError("No Table of Contents found in the PDF to determine splits.")

        chapters: list[dict[str, Any]] = []
        for item in toc:
            lvl, title, page = item
            is_chapter_node = "chapter" in title.lower() or lvl == 1
            is_new_page = not chapters or chapters[-1]["page"] != page
            if is_chapter_node and is_new_page:
                chapters.append({"title": title, "page": page})

        if not chapters:
            raise ValueError("Could not identify valid chapter boundaries in the TOC.")

        output_dir.mkdir(parents=True, exist_ok=True)
        generated: list[Chapter] = []

        print(f"[Orchestrator] Identified {len(chapters)} chapters. Slicing PDF...")

        for i, chap in enumerate(chapters):
            start_page = chap["page"] - 1
            end_page = chapters[i + 1]["page"] - 2 if i + 1 < len(chapters) else len(doc) - 1

            chap_num = f"{i:02d}"
            match = re.search(r"Chapter (\d+)", chap["title"], re.IGNORECASE)
            if match:
                chap_num = f"{int(match.group(1)):02d}"

            clean_title = sanitize_filename(chap["title"].replace(":", " -"))
            file_name = f"{chap_num}-{clean_title}.pdf"
            out_path = output_dir / file_name

            if out_path.exists():
                print(f"  -> Skipping slice (already exists): {file_name}")
            else:
                print(f"  -> Slicing {file_name} (Pages {start_page + 1} to {end_page + 1})")
                chap_doc = pymupdf.open()
                chap_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
                chap_doc.save(out_path)
                chap_doc.close()

            lower_title = clean_title.lower()
            is_denied = not all_mechanics and not is_substantive_chapter(clean_title)
            is_explicit_mechanics = any(kw in lower_title for kw in MECHANICS_KEYWORDS)
            is_adventure = adventure_mode and (
                any(kw in lower_title for kw in ADVENTURE_KEYWORDS) or not is_explicit_mechanics
            )
            is_lore = include_lore and any(kw in lower_title for kw in LORE_KEYWORDS) and not is_explicit_mechanics

            if is_denied:
                chap_mode = "skip"
            elif is_adventure:
                chap_mode = "adventure"
            elif is_lore:
                chap_mode = "lore"
            else:
                chap_mode = "mechanics"

            needs_gemini = chap_mode != "skip"
            generated.append(Chapter(path=out_path, title=clean_title, mechanics=needs_gemini, mode=chap_mode))
    finally:
        doc.close()

    return generated


class LazyConverter:
    """Creates the Docling converter only when first needed, so fully-cached reruns skip model loading."""

    def __init__(self) -> None:
        self._converter: DocumentConverter | None = None

    def get(self) -> DocumentConverter:
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter


async def process_chapter_async(
    chap: Chapter,
    md_out_dir: Path,
    vault_dir: Path,
    converter: LazyConverter,
    sourcebook: str,
    *,
    force: bool,
    docling_only: bool,
    chunk_size: int,
    gemini_strategy: str = "quality",
    max_concurrency: int = 3,
) -> Path:
    """Run the extraction pipeline for one chapter and return the path of its primary Markdown file."""
    stem = chap.path.stem
    docling_md = tagged_md_path(md_out_dir, stem, DOCLING_TAG)

    # Phase 1: Docling Ground Truth Extraction
    print("  -> Phase 1: Docling Extraction (Ground Truth & Lore)")
    if docling_md.exists() and not force:
        print(f"       -> Skipping (already exists): {docling_md.name}")
    else:
        convert_pdf(chap.path, docling_md, converter=converter.get(), force=force)

    # Apply inline symbol and glyph patches to the docling chapter file
    patch_file(docling_md)

    # Phase 2 & 3: Async Gemini Vision & OKF Concept Shredding
    if chap.mechanics and not docling_only:
        gemini_md = tagged_md_path(md_out_dir, stem, GEMINI_TAG)
        prompt_label = getattr(chap, "mode", "mechanics").capitalize()
        print(f"  -> Phase 2: Async Gemini Vision Extraction (Mode: {prompt_label})")
        if gemini_md.exists() and not force:
            print(f"       -> Skipping (already exists): {gemini_md.name}")
        else:
            chap_mode = getattr(chap, "mode", "mechanics")
            if chap_mode == "adventure":
                prompt_to_use = ADVENTURE_PROMPT
            elif chap_mode == "lore":
                prompt_to_use = LORE_PROMPT
            else:
                prompt_to_use = DEFAULT_PROMPT

            await extract_pdf_async(
                chap.path,
                gemini_md,
                chunk_size=chunk_size,
                strategy=gemini_strategy,
                max_concurrency=max_concurrency,
                prompt=prompt_to_use,
            )

        print("  -> Phase 3: Shredding into OKF Vault")
        shredded = shred_chapter(
            docling_md_path=docling_md,
            gemini_output_path=gemini_md,
            vault_dir=vault_dir,
            default_sourcebook=sourcebook,
        )
        print(f"       -> Created/updated {len(shredded)} atomic concept file(s).")
    elif chap.mechanics:
        print("  -> Pipeline routing: --docling-only set. Bypassing Gemini & OKF shredding.")
    else:
        print("  -> Pipeline routing: Narrative chapter (bypassing Gemini & OKF shredding).")

    return docling_md


def process_chapter(
    chap: Chapter,
    md_out_dir: Path,
    converter: LazyConverter,
    *,
    force: bool = False,
    docling_only: bool = False,
    chunk_size: int = 5,
    gemini_strategy: str = "quality",
    sourcebook: str = "TTRPG Rulebook",
    vault_dir: Path | None = None,
) -> Path:
    """Synchronous compatibility wrapper for single-chapter processing."""
    effective_vault = vault_dir or (md_out_dir.parent / "okf_vault")
    return asyncio.run(
        process_chapter_async(
            chap=chap,
            md_out_dir=md_out_dir,
            vault_dir=effective_vault,
            converter=converter,
            sourcebook=sourcebook,
            force=force,
            docling_only=docling_only,
            chunk_size=chunk_size,
            gemini_strategy=gemini_strategy,
        )
    )


async def run_pipeline_async(args: argparse.Namespace) -> None:
    base_dir = args.output if args.output else args.pdf_path.parent / "Extracted_Rulebook"
    pdf_split_dir = base_dir / "PDF_Chapters"
    md_out_dir = base_dir / "Markdown"
    vault_dir = base_dir / "okf_vault"
    bundles_dir = base_dir / "bundles"

    md_out_dir.mkdir(parents=True, exist_ok=True)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 1. Slice or select document
    if getattr(args, "no_split", False):
        print(f"\n[Orchestrator] Processing {args.pdf_path.name} as a single document (--no-split)...")
        chap_mode = (
            "adventure"
            if getattr(args, "adventure_mode", False)
            else ("lore" if getattr(args, "include_lore", False) else "mechanics")
        )
        chapters = [Chapter(path=args.pdf_path, title=args.pdf_path.stem, mechanics=True, mode=chap_mode)]
    else:
        try:
            chapters = split_pdf_by_chapters(
                args.pdf_path,
                pdf_split_dir,
                all_mechanics=getattr(args, "all_mechanics", False),
                include_lore=getattr(args, "include_lore", False),
                adventure_mode=getattr(args, "adventure_mode", False),
            )
        except ValueError as e:
            sys.exit(f"[!] Error: {e}")

    print("\n" + "=" * 50)
    print(" PIPELINE EXECUTION STARTING (OKF ARCHITECTURE)")
    print("=" * 50)

    reset_run_report()
    converter = LazyConverter()
    failures: list[tuple[str, str]] = []

    # 2. Extract chapters and shred into vault
    for idx, chap in enumerate(chapters, 1):
        print(f"\n[{idx}/{len(chapters)}] Processing: {chap.path.name}")
        try:
            final_md = await process_chapter_async(
                chap,
                md_out_dir,
                vault_dir,
                converter,
                sourcebook=args.sourcebook,
                force=args.force,
                docling_only=args.docling_only,
                chunk_size=args.chunk_size,
                gemini_strategy=args.gemini_strategy,
                max_concurrency=args.concurrency,
            )
            print(f"  [SUCCESS] {chap.path.name} -> {final_md.name}")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAILED] {chap.path.name}: {e}", file=sys.stderr)
            failures.append((chap.path.name, str(e)))

    # 3. Cross-link the OKF Vault
    if not args.docling_only and vault_dir.exists():
        print("\n" + "=" * 50)
        print(" CROSS-LINKING OKF VAULT")
        print("=" * 50)
        linked_count = cross_link_vault(vault_dir)
        print(f"  -> Cross-linked concept references across {linked_count} file(s).")

        # 4. Generate NotebookLM category bundles
        print("\n" + "=" * 50)
        print(" GENERATING NOTEBOOKLM BUNDLES")
        print("=" * 50)
        bundles = bundle_vault(vault_dir, bundles_dir)
        print(f"  -> Generated {len(bundles)} category bundle(s):")
        for b in bundles:
            print(f"     - {b.name}")

    # 5. Print and save Gemini Extraction Run Report
    if not args.docling_only:
        report_text = get_run_report().format_report()
        report_path = base_dir / "run_report.md"
        report_path.write_text(report_text, encoding="utf-8")
        print("\n" + "=" * 50)
        print(" GEMINI EXTRACTION RUN REPORT")
        print("=" * 50)
        print(report_text)
        print(f"  -> Saved Run Report to: {report_path}")

    print("\n" + "=" * 50)
    if failures:
        print(f" FINISHED WITH {len(failures)} FAILED CHAPTER(S):")
        for name, err in failures:
            print(f"   - {name}: {err}")
        print(" Re-run the same command to retry; completed work is cached.")
    else:
        print(" ALL CHAPTERS PROCESSED SUCCESSFULLY!")
    print(f" Outputs saved to: {base_dir}")
    print("=" * 50)

    if failures:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="TTRPG Open Knowledge Format (OKF) Pipeline Orchestrator")
    parser.add_argument("pdf_path", type=clean_path, help="Path to the unsplit Master PDF.")
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help="Output directory for generated files (default: '<pdf_dir>/Extracted_Rulebook').",
    )
    parser.add_argument(
        "-s",
        "--sourcebook",
        type=str,
        default="Cosmere RPG",
        help="Sourcebook or publication name for OKF concept namespacing (default: 'Cosmere RPG').",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-run Docling and Gemini extraction even if their outputs already exist.",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Process the PDF as a single document without splitting into chapter PDFs.",
    )
    parser.add_argument(
        "--all-mechanics",
        action="store_true",
        help="Extract OKF concepts for all chapters, ignoring keyword filtering.",
    )
    parser.add_argument(
        "--include-lore",
        action="store_true",
        help="Extract worldbuilding, factions, and lore chapters into OKFLoreEntry concepts.",
    )
    parser.add_argument(
        "--adventure-mode",
        action="store_true",
        help="Extract interactive adventure nodes and encounters into OKFAdventureNode concepts and compile GM Campaign Guide.",  # noqa: E501
    )
    parser.add_argument(
        "--docling-only",
        action="store_true",
        help="Skip the Gemini and OKF phases for every chapter (e.g. when out of API quota).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5,
        help="Pages per Gemini request (default: 5).",
    )
    parser.add_argument(
        "--strategy",
        "--gemini-strategy",
        dest="gemini_strategy",
        choices=["pro", "quality", "quota"],
        default="quality",
        help="Gemini model cascade strategy: 'pro' prefers Pro models; 'quality' prefers Flash models; "
        "'quota' prefers Flash-Lite models (default: quality).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Maximum concurrent chunk requests to Gemini API (default: 2).",
    )
    args = parser.parse_args()

    if not args.pdf_path.is_file():
        sys.exit(f"Error: Master PDF not found: {args.pdf_path}")

    asyncio.run(run_pipeline_async(args))


if __name__ == "__main__":
    main()
