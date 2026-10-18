import argparse
import sys
from pathlib import Path

from docling.document_converter import DocumentConverter

from ttrpg_markdown_pipeline.common import DOCLING_TAG, clean_path, resolve_md_output


def convert_pdf(
    pdf_path: Path,
    out_file: Path,
    converter: DocumentConverter | None = None,
    force: bool = False,
) -> Path:
    """Convert a single PDF to Markdown with Docling and write it to `out_file`.

    Pass a shared `converter` when converting many files so Docling's models load only once.
    Skips the conversion if `out_file` already exists, unless `force` is True.
    """
    if out_file.exists() and not force:
        print(f"       -> Skipping (already exists): {out_file.name}")
        return out_file

    out_file.parent.mkdir(parents=True, exist_ok=True)
    converter = converter or DocumentConverter()
    result = converter.convert(str(pdf_path))
    out_file.write_text(result.document.export_to_markdown(), encoding="utf-8")
    print(f"       -> Saved to {out_file.name}")
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDF rulebook chapters to Markdown using Docling.")
    parser.add_argument(
        "input_path",
        type=clean_path,
        help="Path to a single PDF file OR a folder containing PDF files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help=(
            "Output directory, or a .md file path when converting a single PDF "
            "(defaults to '<input_dir>/md' for folders, or next to the PDF for single files)."
        ),
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing .md files instead of skipping them.",
    )
    args = parser.parse_args()

    if not args.input_path.exists():
        sys.exit(f"Error: Path does not exist: {args.input_path}")

    # Determine files to process and the default target directory
    if args.input_path.is_file():
        if args.input_path.suffix.lower() != ".pdf":
            sys.exit(f"Error: {args.input_path} is not a PDF file.")
        pdf_files = [args.input_path]
        default_dir = args.input_path.parent
    else:
        pdf_files = sorted(args.input_path.glob("*.pdf"))
        if not pdf_files:
            sys.exit(f"Error: No PDF files found in {args.input_path}")
        default_dir = args.input_path / "md"
        if args.output is not None and args.output.suffix.lower() == ".md":
            sys.exit("Error: --output must be a directory when converting a folder of PDFs.")

    targets = [(pdf, resolve_md_output(args.output, default_dir, pdf.stem, DOCLING_TAG)) for pdf in pdf_files]
    print(f"Found {len(pdf_files)} PDF(s) to process. Output target: {targets[0][1].parent}\n")
    converter = DocumentConverter()

    for idx, (pdf_path, out_file) in enumerate(targets, 1):
        print(f"[{idx}/{len(targets)}] Converting: {pdf_path.name}...")
        try:
            convert_pdf(pdf_path, out_file, converter=converter, force=args.force)
        except Exception as e:  # noqa: BLE001
            print(f"       -> Failed to process {pdf_path.name}: {e}", file=sys.stderr)

    print("\nDocling processing complete.")


if __name__ == "__main__":
    main()
