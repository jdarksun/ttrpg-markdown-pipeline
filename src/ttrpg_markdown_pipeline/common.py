"""Shared helpers and naming conventions used across the pipeline modules."""

from pathlib import Path

DOCLING_TAG = " - DOCLING"
GEMINI_TAG = " - GEMINI"
MERGED_TAG = " - MERGED"
ALL_TAGS = (DOCLING_TAG, GEMINI_TAG, MERGED_TAG)


def clean_path(path_str: str) -> Path:
    """Strip accidental quotes caused by Windows shell trailing backslash escapes."""
    return Path(path_str.rstrip("\"'").strip())


def strip_tags(stem: str) -> str:
    """Remove any pipeline tag (e.g. ' - DOCLING') from the end of a file stem."""
    for tag in ALL_TAGS:
        if stem.endswith(tag):
            return stem[: -len(tag)]
    return stem


def tagged_md_path(out_dir: Path, stem: str, tag: str) -> Path:
    """Return `<out_dir>/<stem><tag>.md`, without adding the tag twice."""
    base = strip_tags(stem)
    return out_dir / f"{base}{tag}.md"


def resolve_md_output(output: Path | None, default_dir: Path, stem: str, tag: str) -> Path:
    """Resolve a user-supplied `-o/--output` value to a concrete tagged `.md` file path.

    - None                     -> `<default_dir>/<stem><tag>.md`
    - anything not ending .md  -> treated as a directory: `<output>/<stem><tag>.md`
    - a `.md` file path        -> that file, with the tag appended to its stem if missing

    Note: `Path()` drops trailing slashes, so the `.md` suffix (not a trailing slash) is
    what distinguishes a file from a directory.
    """
    if output is None:
        return tagged_md_path(default_dir, stem, tag)
    if output.is_dir() or output.suffix.lower() != ".md":
        return tagged_md_path(output, stem, tag)
    return tagged_md_path(output.parent, output.stem, tag)
