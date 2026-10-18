import argparse
import re
import sys
from pathlib import Path

from ttrpg_markdown_pipeline.common import DOCLING_TAG, GEMINI_TAG, MERGED_TAG, clean_path, strip_tags, tagged_md_path
from ttrpg_markdown_pipeline.rules.cosmere import UNIVERSAL_INLINE_FIXES

NON_TALENT_HEADERS: set[str] = {
    # Section overviews & sidebars
    "using metalborn paths",
    "using paths and talents",
    "metalborn path options",
    "choosing powers",
    "choosing a snap or heritage talent",
    "using invested skills",
    "hemalurgy in the cosmere rpg",
    "randomizing your metalborn path",
    "randomizing your misting power",
    "randomizing your feruchemical power",
    "randomizing your twinborn powers",
    "burning rare metals",
    "managing metals",
    "consuming impure metal",
    "becoming depleted of rare metals",
    "metallic art discovery",
    "allomancy discovery",
    "feruchemy discovery",
    "spending investiture",
    "refreshing metal reserves",
    "metals from other sources",
    "acquiring metalminds",
    "storing traits in metalminds",
    "tapping metalminds",
    "multiple metalminds",
    "maintaining metalminds",
    "metalborn goals and rewards",
    "allomancy: using investiture",
    "allomancy: training in the allomantic arts",
    "feruchemy: using metalminds",
    "feruchemy: constructing a metalmind",
    "intuitive atium",
    "exploring resonances",
    "compounders",
    "manifestations of savantism",
    # History headers
    "mistborn history",
    "feruchemist history",
    "ferring history",
    "twinborn history",
    # Path & tree intro headers
    "misting",
    "mistborn",
    "feruchemist",
    "ferring",
    "twinborn",
    "misting talents",
    "mistborn talents",
    "feruchemist talents",
    "ferring talents",
    "twinborn talents",
    # Flowchart / table legends
    "icon meaning",
    "icon",
    "meaning",
}


class TalentMetadata(dict[str, dict[str, str]]):
    """Stores talent metadata as a dictionary of {clean_name: default_entry},
    while tracking multiple occurrences in encounter order for sequential resolution.
    """

    def __init__(self) -> None:
        super().__init__()
        self._occurrences: dict[str, list[dict[str, str]]] = {}
        self._consumed: dict[str, int] = {}

    def add_entry(self, clean_name: str, entry: dict[str, str]) -> None:
        if clean_name not in self._occurrences:
            self._occurrences[clean_name] = []
            self[clean_name] = entry  # Default for dict backward compatibility
        self._occurrences[clean_name].append(entry)

    def get_occurrence(self, lookup_name: str, docling_prereq: str | None = None) -> dict[str, str] | None:
        entries = self._occurrences.get(lookup_name)
        if not entries:
            # Substring match if exact match not found
            for k, v in self._occurrences.items():
                if k == lookup_name or k in lookup_name or lookup_name in k:
                    entries = v
                    lookup_name = k
                    break

        if not entries:
            return None

        # If multiple entries and docling_prereq provided, match prerequisite keywords
        if len(entries) > 1 and docling_prereq:
            clean_dp = " ".join(docling_prereq.lower().split())
            for ent in entries:
                clean_ep = ent["prereq"].lower()
                if (
                    clean_dp in clean_ep
                    or clean_ep in clean_dp
                    or clean_ep[:10] in clean_dp
                    or any(
                        w in clean_dp
                        for w in clean_ep.split()
                        if len(w) > 4 and w not in ("talent", "prerequisite", "prerequisites")
                    )
                ):
                    return ent

        # Sequential cursor consumption
        idx = self._consumed.get(lookup_name, 0)
        selected_idx = min(idx, len(entries) - 1)
        self._consumed[lookup_name] = idx + 1
        return entries[selected_idx]

    def all_occurrences(self) -> list[dict[str, str]]:
        result = []
        for entries in self._occurrences.values():
            result.extend(entries)
        return result


def extract_talent_metadata(gemini_text: str) -> TalentMetadata:
    """Extracts a lookup table of {talent_name: {prereq, act}} from Gemini output without crossing header boundaries."""
    pattern = re.compile(
        r"#{2,4}\s+([A-Za-z0-9 ’'!\-()]+?)(?:\s*\([^)]*\))?\r?\n"
        r"((?:(?!^\s*#{1,4}\s).)*?)"
        r"(?:[-*]\s*)?\*\*Prerequisites?:\*\*\s*(.*?)\r?\n\s*"
        r"(?:[-*]\s*)?\*\*Activation:\*\*\s*[`*]?(\[[^\]]+\]|"
        r"Special Activation|Special|Passive|Always Active)[`*]?",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    metadata = TalentMetadata()
    for m in pattern.finditer(gemini_text):
        raw_name = m.group(1).strip()
        clean_name = re.sub(r"\s*\([^)]*\)", "", raw_name).strip().lower()
        if clean_name in NON_TALENT_HEADERS or not any(c.isalpha() for c in clean_name):
            continue

        prereq = m.group(3).strip("`* ")
        act = m.group(4).strip("`* ")

        if act in ("Special", "Special Activation", "[Special Activation]"):
            act = "[Special Activation]"
        elif act in ("Passive", "Always Active", "[Passive]", "[Always Active]"):
            act = "[Passive]"

        metadata.add_entry(
            clean_name,
            {
                "raw_name": raw_name,
                "prereq": prereq,
                "act": act,
            },
        )
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

    # Primary Pass: Matches single-line compressed Docling headers AND multiline split headers
    header_regex = re.compile(
        r"^[ \t]*(?:##\s*|###\s*)?([A-Za-z0-9 ’'!\-()]+?)\s*\n*"
        r"(?:(?:##\s*|###\s*|[-*]\s*)?Prerequisites?:\s*((?:(?!^[ \t]*##|Activation:).)*?))?"
        r"(?:##\s*|###\s*|[-*]\s*)?Activation:\s*$",
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )

    matched_talents: set[str] = set()

    def format_header(match: re.Match[str]) -> str:
        raw_name = match.group(1).strip()
        clean_raw_name = re.sub(r"^[-*#\s]+", "", raw_name).strip()
        lookup_name = re.sub(r"\s*\([^)]*\)", "", clean_raw_name).strip().lower()

        # Abort if name is invalid, a lone dash/bullet, lacks letters, or is a known non-talent section
        if (
            not clean_raw_name
            or clean_raw_name in ("-", "*")
            or not re.search(r"[A-Za-z]{2,}", clean_raw_name)
            or lookup_name in NON_TALENT_HEADERS
        ):
            return match.group(0)

        matched_talents.add(lookup_name)

        docling_prereq = match.group(2)
        prereq = " ".join(docling_prereq.split()) if docling_prereq else "None"
        act = "[Special Activation]"

        # Inject clean Gemini metadata if matched (occurrence-aware)
        match_meta = metadata.get_occurrence(lookup_name, docling_prereq=docling_prereq)
        if match_meta:
            act = match_meta["act"]
            if match_meta["prereq"].lower() != "none":
                prereq = match_meta["prereq"]

        out = [f"### {clean_raw_name}"]
        if prereq and prereq.lower() != "none":
            out.append(f"- **Prerequisites:** {prereq}")
        elif prereq.lower() == "none":
            out.append("- **Prerequisites:** None")
        out.append(f"- **Activation:** {act}\n")
        return "\n".join(out)

    patched_text = header_regex.sub(format_header, docling_text)

    # Fallback Pass: Fix talents that lost their "Activation:" string entirely in Docling
    # (Skip any talents already converted in the primary pass to prevent converting flowchart summaries)
    for v in metadata.all_occurrences():
        clean_v = re.sub(r"^[-*#\s]+", "", v["raw_name"])
        clean_v = re.sub(r"\s*\([^)]*\)", "", clean_v).strip().lower()
        if clean_v in NON_TALENT_HEADERS or clean_v in matched_talents:
            continue
        raw_escaped = re.escape(v["raw_name"]).replace(r"\'", "['’]").replace("’", "['’]")
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
