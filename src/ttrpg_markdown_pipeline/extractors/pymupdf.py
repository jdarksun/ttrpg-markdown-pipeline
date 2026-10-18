import argparse
from pathlib import Path

import pymupdf
import pymupdf4llm

from ttrpg_markdown_pipeline.common import clean_path


def extract_pdf(pdf_path: Path, output_path: Path) -> Path:
    """Quick layout-aware extraction of PDF text to Markdown via PyMuPDF4LLM with PyMuPDF fallback."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {pdf_path.name} -> {output_path.name}...")
    try:
        md_text = pymupdf4llm.to_markdown(str(pdf_path))
    except (ImportError, OSError):
        # Graceful fallback if Application Control / AppLocker blocks third-party OCR DLLs (e.g. shapely)
        doc = pymupdf.open(pdf_path)
        pages_text = [doc[i].get_text("text") for i in range(len(doc))]
        doc.close()
        md_text = "\n\n".join(pages_text)
    output_path.write_text(md_text, encoding="utf-8")
    print("Done!")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown via layout heuristics using pymupdf4llm.")
    parser.add_argument("pdf_path", type=clean_path, help="Path to input PDF")
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help="Path to output Markdown file (defaults to <pdf_stem>.md)",
    )
    args = parser.parse_args()

    if not args.pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {args.pdf_path}")

    output_path = args.output or args.pdf_path.with_suffix(".md")
    extract_pdf(args.pdf_path, output_path)


if __name__ == "__main__":
    main()
