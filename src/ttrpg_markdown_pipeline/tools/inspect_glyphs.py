"""Diagnostic tool: find icon glyphs (Private Use Area characters / icon fonts) on PDF pages.

Use this to discover which Unicode code points and fonts a rulebook uses for its action icons,
so they can be mapped in the patch/merge rules.
"""

import argparse
import sys

import pymupdf

from ttrpg_markdown_pipeline.common import clean_path


def find_glyphs(pdf_path: str, search: str) -> None:
    doc = pymupdf.open(pdf_path)

    # Only inspect pages containing the search phrase (e.g. the Action Economy rules)
    for page in doc.pages():
        text_instances = page.search_for(search)
        if text_instances:
            # Extract raw text spans with font metadata
            blocks = page.get_text("rawdict")["blocks"]
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        # Check for unusual fonts or Private Use Area Unicode characters
                        for c in span.get("chars", []):
                            char = c["c"]
                            code = ord(char)
                            if 0xE000 <= code <= 0xF8FF or "Icon" in span.get("font", ""):
                                print(
                                    f"Page {page.number + 1}: Found Glyph: '{char}' (Unicode: U+{code:04X}) "
                                    f"in Font: '{span['font']}'"
                                )
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="List icon glyphs / Private Use Area characters in a PDF.")
    parser.add_argument("pdf_path", type=clean_path, help="Path to the source PDF (not the Markdown output).")
    parser.add_argument(
        "-s",
        "--search",
        default="Actions (",
        help="Only scan pages containing this text (default: 'Actions (').",
    )
    args = parser.parse_args()

    if args.pdf_path.suffix.lower() != ".pdf" or not args.pdf_path.is_file():
        sys.exit(f"Error: PDF not found: {args.pdf_path}")

    find_glyphs(str(args.pdf_path), args.search)


if __name__ == "__main__":
    main()
