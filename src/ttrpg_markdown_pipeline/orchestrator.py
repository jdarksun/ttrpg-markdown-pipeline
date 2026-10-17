import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from docling.document_converter import DocumentConverter

from ttrpg_markdown_pipeline.common import DOCLING_TAG, GEMINI_TAG, MERGED_TAG, clean_path, tagged_md_path
from ttrpg_markdown_pipeline.extractors.docling import convert_pdf
from ttrpg_markdown_pipeline.extractors.gemini import extract_pdf
from ttrpg_markdown_pipeline.processors.merge import merge_chapter
from ttrpg_markdown_pipeline.processors.patch import patch_file
from ttrpg_markdown_pipeline.rules.cosmere import MECHANICS_KEYWORDS


@dataclass
class Chapter:
    path: Path
    title: str
    mechanics: bool


def sanitize_filename(name: str) -> str:
    """Removes invalid filename characters."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def split_pdf_by_chapters(pdf_path: Path, output_dir: Path) -> list[Chapter]:
    """Reads the TOC, splits the PDF into chapter files, and returns their metadata.

    Raises ValueError if the PDF has no usable Table of Contents.
    """
    print(f"\n[Orchestrator] Reading Table of Contents from {pdf_path.name}...")
    doc = pymupdf.open(pdf_path)
    try:
        toc = doc.get_toc()

        if not toc:
            raise ValueError("No Table of Contents found in the PDF to determine splits.")

        # Find the main structural nodes (usually Level 1, or Level 2 if nested under 'Parts')
        # We'll look specifically for "Chapter" or assume top-level items are the splits.
        chapters: list[dict[str, Any]] = []
        for item in toc:
            lvl, title, page = item
            # Some RPG PDFs use Level 1 for "Part 1" and Level 2 for "Chapter 4"
            is_chapter_node = "chapter" in title.lower() or lvl == 1
            # Avoid duplicating nested chapters if we already matched them
            is_new_page = not chapters or chapters[-1]["page"] != page
            if is_chapter_node and is_new_page:
                chapters.append({"title": title, "page": page})

        if not chapters:
            raise ValueError("Could not identify valid chapter boundaries in the TOC.")

        output_dir.mkdir(parents=True, exist_ok=True)
        generated: list[Chapter] = []

        print(f"[Orchestrator] Identified {len(chapters)} chapters. Slicing PDF...")

        for i, chap in enumerate(chapters):
            start_page = chap["page"] - 1  # PyMuPDF pages are 0-indexed, TOC is 1-indexed

            # End page is the start of the next chapter, or the end of the document
            end_page = chapters[i + 1]["page"] - 2 if i + 1 < len(chapters) else len(doc) - 1

            # Format: 04-Heroic_Paths.pdf
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

            # Determine routing strategy
            needs_mechanics = any(kw in clean_title.lower() for kw in MECHANICS_KEYWORDS)

            generated.append(Chapter(path=out_path, title=clean_title, mechanics=needs_mechanics))
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


def process_chapter(
    chap: Chapter,
    md_out_dir: Path,
    converter: LazyConverter,
    *,
    force: bool,
    docling_only: bool,
    chunk_size: int,
) -> Path:
    """Run the extraction pipeline for one chapter and return the path of its final Markdown file."""
    stem = chap.path.stem
    docling_md = tagged_md_path(md_out_dir, stem, DOCLING_TAG)

    # Step A: Docling Extraction (Runs for ALL chapters)
    print("  -> Phase 1: Docling Extraction (Ground Truth & Lore)")
    if docling_md.exists() and not force:
        print(f"       -> Skipping (already exists): {docling_md.name}")
    else:
        convert_pdf(chap.path, docling_md, converter=converter.get(), force=force)

    final_md = docling_md

    # Step B & C: Gemini Vision & Mechanics Merge (Runs ONLY for mechanics chapters)
    if chap.mechanics and not docling_only:
        gemini_md = tagged_md_path(md_out_dir, stem, GEMINI_TAG)
        print("  -> Phase 2: Gemini Vision Extraction (Action Economy & Mechanics)")
        if gemini_md.exists() and not force:
            print(f"       -> Skipping (already exists): {gemini_md.name}")
        else:
            # Resumes from per-chapter chunk cache if a previous run was interrupted
            extract_pdf(chap.path, gemini_md, chunk_size=chunk_size)

        print("  -> Phase 3: Merging Docling and Gemini")
        final_md = tagged_md_path(md_out_dir, stem, MERGED_TAG)
        merge_chapter(docling_md, gemini_md, final_md)
    elif chap.mechanics:
        print("  -> Pipeline routing: --docling-only set. Bypassing Gemini/Merge.")
    else:
        print("  -> Pipeline routing: No mechanics keywords detected. Bypassing Gemini/Merge.")

    # Step D: Glyph/icon text repairs. Must run AFTER the merge: it rewrites blank
    # 'Activation:' lines, which merge_mechanics relies on to locate talent headers.
    print("  -> Phase 4: Patching icon/glyph artifacts")
    patch_file(final_md)

    return final_md


def main() -> None:
    parser = argparse.ArgumentParser(description="Cosmere RPG Full Pipeline Orchestrator")
    parser.add_argument("pdf_path", type=clean_path, help="Path to the unsplit Master PDF.")
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help="Output directory for generated files (default: '<pdf_dir>/Extracted_Rulebook').",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-run Docling and Gemini extraction even if their outputs already exist.",
    )
    parser.add_argument(
        "--docling-only",
        action="store_true",
        help="Skip the Gemini and merge phases for every chapter (e.g. when out of API quota).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8,
        help="Pages per Gemini request (default: 8).",
    )
    args = parser.parse_args()

    if not args.pdf_path.is_file():
        sys.exit(f"Error: Master PDF not found: {args.pdf_path}")

    base_dir = args.output if args.output else args.pdf_path.parent / "Extracted_Rulebook"
    pdf_split_dir = base_dir / "PDF_Chapters"
    md_out_dir = base_dir / "Markdown"
    md_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Slice the PDF
    try:
        chapters = split_pdf_by_chapters(args.pdf_path, pdf_split_dir)
    except ValueError as e:
        sys.exit(f"[!] Error: {e}")

    print("\n" + "=" * 50)
    print(" PIPELINE EXECUTION STARTING")
    print("=" * 50)

    converter = LazyConverter()  # Docling models load once, shared across chapters
    failures: list[tuple[str, str]] = []

    for idx, chap in enumerate(chapters, 1):
        print(f"\n[{idx}/{len(chapters)}] Processing: {chap.path.name}")
        try:
            final_md = process_chapter(
                chap,
                md_out_dir,
                converter,
                force=args.force,
                docling_only=args.docling_only,
                chunk_size=args.chunk_size,
            )
            print(f"  [SUCCESS] {chap.path.name} -> {final_md.name}")
        except Exception as e:  # noqa: BLE001 - keep going so one bad chapter doesn't stop the book
            print(f"  [FAILED] {chap.path.name}: {e}", file=sys.stderr)
            failures.append((chap.path.name, str(e)))

    print("\n" + "=" * 50)
    if failures:
        print(f" FINISHED WITH {len(failures)} FAILED CHAPTER(S):")
        for name, err in failures:
            print(f"   - {name}: {err}")
        print(" Re-run the same command to retry; completed work is cached.")
    else:
        print(" ALL CHAPTERS PROCESSED SUCCESSFULLY!")
    print(f" Outputs saved to: {md_out_dir}")
    print("=" * 50)

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
