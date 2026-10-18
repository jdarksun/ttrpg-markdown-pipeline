import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ttrpg_markdown_pipeline.common import DOCLING_TAG, GEMINI_TAG, clean_path, tagged_md_path
from ttrpg_markdown_pipeline.rules.cosmere import patch_cosmere_rules


def patch_file(md_file: Path, patcher: Callable[[str], str] = patch_cosmere_rules) -> bool:
    """Apply a patching function to a single Markdown file in place. Returns True if changed."""
    original = md_file.read_text(encoding="utf-8")
    patched = patcher(original)
    if patched == original:
        print(f"  [No change] {md_file.name}")
        return False
    md_file.write_text(patched, encoding="utf-8")
    print(f"  [Patched] {md_file.name}")
    return True


def find_final_outputs(target_dir: Path) -> list[Path]:
    """Return the Markdown files in `target_dir` that are safe to patch.

    Skips DOCLING/GEMINI intermediates that still have a pending merge partner,
    because patching blank 'Activation:' lines would break `merge_mechanics` header matching.
    """
    files = []
    for md_file in sorted(target_dir.glob("*.md")):
        stem = md_file.stem
        if stem.endswith(GEMINI_TAG):
            continue
        if stem.endswith(DOCLING_TAG) and tagged_md_path(target_dir, stem, GEMINI_TAG).exists():
            continue  # Mechanics chapter: patch its MERGED file instead
        files.append(md_file)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply rulebook icon/glyph text repairs to Markdown files.")
    parser.add_argument("target", type=clean_path, help="A Markdown file, or a directory of Markdown files.")
    parser.add_argument(
        "--include-intermediates",
        action="store_true",
        help="In directory mode, also patch DOCLING/GEMINI files that are awaiting a merge.",
    )
    args = parser.parse_args()

    if args.target.is_file():
        patch_file(args.target)
        return
    if not args.target.is_dir():
        sys.exit(f"Not found: {args.target}")

    md_files = sorted(args.target.glob("*.md")) if args.include_intermediates else find_final_outputs(args.target)
    print(f"Patching {len(md_files)} markdown files in {args.target}...")
    for md_file in md_files:
        patch_file(md_file)
    print("Patching complete.")


if __name__ == "__main__":
    main()
