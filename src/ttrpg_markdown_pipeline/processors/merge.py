import argparse
import re
import sys
from pathlib import Path

from ttrpg_markdown_pipeline.common import DOCLING_TAG, GEMINI_TAG, MERGED_TAG, clean_path, strip_tags, tagged_md_path
from ttrpg_markdown_pipeline.rules.cosmere import UNIVERSAL_INLINE_FIXES


def extract_talent_metadata(gemini_text: str) -> dict[str, dict[str, str]]:
    """Extracts a lookup table of {talent_name: {prereq, act}} from Gemini output."""
    pattern = re.compile(
        r"#{2,4}\s+([A-Za-z0-9 ’'!\-()]+?)(?:\s*\([^)]*\))?\s*\r?\n[\s\(\S\)]*?"
        r"(?:[-*]\s*)?\*\*Prerequisites?:\*\*\s*(.*?)\r?\n\s*"
        r"(?:[-*]\s*)?\*\*Activation:\*\*\s*[`*]?(\[[^\]]+\]|"
        r"Special Activation|Special|Passive|Always Active)[`*]?",
        re.MULTILINE | re.IGNORECASE,
    )
    metadata = {}
    for m in pattern.finditer(gemini_text):
        raw_name = m.group(1).strip()
        clean_name = re.sub(r"\s*\([^)]*\)", "", raw_name).strip().lower()
        prereq = m.group(2).strip("`* ")
        act = m.group(3).strip("`* ")

        if act in ("Special", "Special Activation"):
            act = "[Special Activation]"
        elif act in ("Passive", "Always Active"):
            act = "[Passive]"

        metadata[clean_name] = {
            "raw_name": raw_name,
            "prereq": prereq,
            "act": act,
        }
    return metadata


def merge_chapter(
    docling_file: Path,
    gemini_file: Path,
    output_file: Path,
    inline_fixes: dict[str, str] | None = None,
) -> None:
    print(f"\nProcessing: {docling_file.stem} + {gemini_file.stem}")
    docling_text = docling_file.read_text(encoding="utf-8")
    gemini_text = gemini_file.read_text(encoding="utf-8")
    fixes = inline_fixes if inline_fixes is not None else UNIVERSAL_INLINE_FIXES

    metadata = extract_talent_metadata(gemini_text)
    print(f"  -> Extracted {len(metadata)} mechanics from Gemini.")

    # Primary Pass: Finds compressed Docling lines (e.g. ## Name Prerequisite: X Activation:)
    header_regex = re.compile(
        r"^(?:##\s*)?([A-Za-z0-9 ’'!\-()]+?)\s*\n*"
        r"(?:(?:##\s*)?Prerequisite:\s*((?:(?!Activation:|Prerequisite:).)*?)\s*\n*)?"
        r"(?:##\s*)?Activation:\s*$",
        re.MULTILINE | re.DOTALL,
    )

    def format_header(match: re.Match[str]) -> str:
        raw_name = match.group(1).strip()
        docling_prereq = match.group(2)
        lookup_name = re.sub(r"\s*\([^)]*\)", "", raw_name).strip().lower()

        act = "[Special Activation]"
        prereq = docling_prereq if docling_prereq else "None"
        prereq = " ".join(prereq.split())  # Flatten inner newlines

        # Inject clean Gemini metadata if matched
        for k, v in metadata.items():
            if k == lookup_name or k in lookup_name or lookup_name in k:
                act = v["act"]
                prereq = v["prereq"]
                break

        out = [f"### {raw_name}"]
        if prereq and prereq.lower() != "none":
            out.append(f"- **Prerequisites:** {prereq}")
        elif prereq.lower() == "none":
            out.append("- **Prerequisites:** None")
        out.append(f"- **Activation:** {act}\n")
        return "\n".join(out)

    patched_text = header_regex.sub(format_header, docling_text)

    # Fallback Pass: Fix talents that lost their "Activation:" string entirely in Docling
    for v in metadata.values():
        raw_escaped = re.escape(v["raw_name"])
        fallback_regex = re.compile(
            rf"^##\s+({raw_escaped}(?:\s*\([^)]*\))?)\s*\n+(?!- \*\*Prerequisites)",
            re.MULTILINE | re.IGNORECASE,
        )

        def fallback_replace(m: re.Match[str], val: dict[str, str] = v) -> str:
            matched_name = m.group(1).strip()
            return f"### {matched_name}\n- **Prerequisites:** {val['prereq']}\n- **Activation:** {val['act']}\n\n"

        patched_text = fallback_regex.sub(fallback_replace, patched_text)

    # Inline Pass: Universal vector symbol repairs
    for raw_regex, fix in fixes.items():
        patched_text = re.sub(raw_regex, fix, patched_text)

    output_file.write_text(patched_text, encoding="utf-8")
    print(f"  -> Merged text saved to: {output_file.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge Docling text accuracy with Gemini action mechanics.")
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Chapter stem (e.g. '04-Heroic_Paths') or a path to one of its DOCLING/GEMINI .md files.",
    )
    parser.add_argument(
        "-d",
        "--dir",
        type=clean_path,
        default=Path.cwd(),
        help="Directory containing markdown files (default: current directory).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Merge all matching Docling and Gemini pairs found in the directory.",
    )
    args = parser.parse_args()

    md_dir = args.dir
    if not md_dir.exists():
        sys.exit(f"Error: Directory does not exist: {md_dir}")

    if args.all:
        docling_files = sorted(md_dir.glob(f"*{DOCLING_TAG}.md"))
        matched_pairs = 0
        for doc_file in docling_files:
            stem = strip_tags(doc_file.stem)
            gem_file = tagged_md_path(md_dir, stem, GEMINI_TAG)
            if gem_file.exists():
                merge_chapter(doc_file, gem_file, tagged_md_path(md_dir, stem, MERGED_TAG))
                matched_pairs += 1
        print(f"\nBatch merge complete: {matched_pairs} chapters processed.")
        return

    if not args.target:
        sys.exit(
            "Error: Provide a chapter stem/path or use '--all'.\nExample: ttrpg-merge 04-Heroic_Paths -d ./Markdown"
        )

    target_path = clean_path(args.target)
    if target_path.suffix.lower() == ".md":
        stem = strip_tags(target_path.stem)
        base_dir = target_path.parent if str(target_path.parent) != "." else md_dir
    else:
        stem = strip_tags(target_path.name)
        base_dir = md_dir

    doc_file = tagged_md_path(base_dir, stem, DOCLING_TAG)
    gem_file = tagged_md_path(base_dir, stem, GEMINI_TAG)
    out_file = tagged_md_path(base_dir, stem, MERGED_TAG)

    if not doc_file.exists():
        sys.exit(f"Error: Missing Docling file: {doc_file}")
    if not gem_file.exists():
        sys.exit(f"Error: Missing Gemini file: {gem_file}")

    merge_chapter(doc_file, gem_file, out_file)


if __name__ == "__main__":
    main()
