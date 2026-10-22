import argparse
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pymupdf
from google import genai
from google.genai import errors

from ttrpg_markdown_pipeline.common import GEMINI_TAG, clean_path, load_env_file, resolve_md_output
from ttrpg_markdown_pipeline.rules.cosmere import DEFAULT_PROMPT

# Default static fallback if API dynamic discovery is unavailable
DEFAULT_DESIRABILITY_PATH = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]
DESIRABILITY_PATH = DEFAULT_DESIRABILITY_PATH

_MODEL_POOL_CACHE: dict[str, list[str]] = {}
_EXHAUSTED_MODELS: set[str] = set()


def discover_model_pool(client: genai.Client | None = None, strategy: str = "quality") -> list[str]:
    """Dynamically queries Gemini API for available models, filtered and sorted by strategy.

    Strategies:
      - 'quality': Prioritizes standard Flash models by version (newest first), then Flash-Lite.
      - 'quota': Prioritizes Flash-Lite models by version (newest first), then standard Flash.

    Results are cached in-memory per strategy so discovery runs at most once per session.
    """
    if strategy in _MODEL_POOL_CACHE:
        return _MODEL_POOL_CACHE[strategy]

    if client is None:
        try:
            load_env_file()
            client = genai.Client()
        except Exception:
            return DEFAULT_DESIRABILITY_PATH

    try:
        pattern = re.compile(r"^gemini-(\d+(?:\.\d+)?)-(flash(?:-lite)?)$")
        matches: list[tuple[str, str, tuple[int, ...]]] = []

        for m in client.models.list():
            if not m.name:
                continue
            clean = m.name.removeprefix("models/")
            res = pattern.match(clean)
            if res and "generateContent" in getattr(m, "supported_actions", []):
                ver_str, flavor = res.groups()
                parts = tuple(int(p) for p in ver_str.split("."))
                if len(parts) == 1:
                    parts = (parts[0], 0)
                matches.append((clean, flavor, parts))

        if not matches:
            return DEFAULT_DESIRABILITY_PATH

        if strategy == "quota":
            # Flash-Lite tier 2, Flash tier 1 -> descending puts Flash-Lite first
            sorted_models = [
                m[0]
                for m in sorted(
                    matches,
                    key=lambda x: (2 if x[1] == "flash-lite" else 1, x[2]),
                    reverse=True,
                )
            ]
        else:
            # Quality: Flash tier 2, Flash-Lite tier 1 -> descending puts Flash first
            sorted_models = [
                m[0]
                for m in sorted(
                    matches,
                    key=lambda x: (2 if x[1] == "flash" else 1, x[2]),
                    reverse=True,
                )
            ]

        _MODEL_POOL_CACHE[strategy] = sorted_models
        return sorted_models
    except Exception as e:
        print(f"[!] Warning: Could not dynamically list Gemini models ({e}). Using static fallback.")
        return DEFAULT_DESIRABILITY_PATH


def is_daily_quota_exhausted(exc: BaseException) -> bool:
    err = str(exc).lower()
    return "please retry in" in err and ("h" in err or "d" in err)


def generate_with_fallback(client: genai.Client, contents: list, model_pool: list[str]) -> tuple[str, str]:
    """Tries generation along the desirability path, cascading on exhaustion or failure.

    Models that hit daily quota limits are cached in-memory and skipped for subsequent calls.
    """
    for model in model_pool:
        if model in _EXHAUSTED_MODELS:
            continue

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] Attempting generation with {model}...")

        # Inner retry loop for transient 503s on the current model
        for attempt in range(1, 6):
            try:
                response = client.models.generate_content(model=model, contents=contents)
                if response.text:
                    return response.text.strip(), model
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [!] {model} returned an empty response. Cascading to next model...")
                break
            except errors.APIError as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if is_daily_quota_exhausted(e):
                    print(f"[{ts}] [!] Daily quota exhausted for {model}. Cascading to next model...")
                    _EXHAUSTED_MODELS.add(model)
                    break  # Break inner loop to trigger next model in pool

                if e.code == 404 or (e.message and "no longer available" in e.message.lower()):
                    print(f"[{ts}] [!] {model} unavailable or deprecated ({e.code}). Cascading to next model...")
                    _EXHAUSTED_MODELS.add(model)
                    break

                if attempt == 5:
                    err_msg = f"{e.code}: {e.message[:60]}" if e.message else str(e.code)
                    print(f"[{ts}] [!] {model} unavailable after 5 attempts ({err_msg}). Cascading...")
                    break

                backoff = min(attempt * 12 if e.code in (429, 503) else attempt * 5, 60)
                err_msg = f"{e.code}: {e.message[:60]}" if e.message else str(e.code)
                print(f"[{ts}] [!] Transient {model} error ({err_msg}). Retrying in {backoff}s ({attempt}/5)...")
                time.sleep(backoff)

    raise RuntimeError("All models in the desirability path failed or exhausted quota.")


def chunk_file_for(cache_dir: Path, start_idx: int, end_idx: int) -> Path:
    return cache_dir / f"chunk_{start_idx + 1:03d}_{end_idx:03d}.md"


def extract_pdf(
    pdf_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 8,
    prompt: str = DEFAULT_PROMPT,
    model_pool: list[str] | None = None,
    strategy: str = "quality",
    client: genai.Client | None = None,
) -> Path:
    """Extract a PDF to Markdown via Gemini Vision, chunked and cached per output file.

    Completed chunks are cached in `<output_dir>/.cache_<output_stem>/`, so an interrupted
    run (e.g. quota exhaustion) resumes where it left off.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Retain or migrate legacy cache directory to preserve prior progress
    legacy_cache = output_path.parent / f".cache_{pdf_path.stem}"
    cache_dir = output_path.parent / f".cache_{output_path.stem}"
    if legacy_cache.exists() and not cache_dir.exists():
        legacy_cache.rename(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    load_env_file()
    try:
        client = client or genai.Client()
    except Exception as e:
        if "API key" in str(e):
            raise ValueError(
                "Gemini API key not found. Please set the GEMINI_API_KEY environment variable "
                "or create a .env file in your project root containing: GEMINI_API_KEY=your_key_here"
            ) from None
        raise

    if model_pool is None:
        model_pool = discover_model_pool(client, strategy=strategy)

    print(f"Active model pool ({strategy}): {', '.join(model_pool)}")
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    chunk_ranges = [(s, min(s + chunk_size, total_pages)) for s in range(0, total_pages, chunk_size)]

    try:
        # Unique temp dir per run, so concurrent runs never clobber each other's chunk PDF
        with tempfile.TemporaryDirectory(prefix="ttrpg_gemini_") as tmp:
            temp_chunk_path = Path(tmp) / "chunk.pdf"

            for start_idx, end_idx in chunk_ranges:
                chunk_file = chunk_file_for(cache_dir, start_idx, end_idx)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                label = f"[{start_idx + 1:02d}–{end_idx:02d}/{total_pages}]"

                if chunk_file.exists():
                    print(f"[{ts}] {label} Found cached chunk. Skipping...")
                    continue

                print(f"[{ts}] {label} Slicing and preparing chunk...")

                chunk_doc = pymupdf.open()
                chunk_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
                chunk_doc.save(temp_chunk_path)
                chunk_doc.close()

                uploaded_file = client.files.upload(file=str(temp_chunk_path))

                text, model_used = generate_with_fallback(
                    client=client,
                    contents=[uploaded_file, prompt],
                    model_pool=model_pool,
                )

                chunk_file.write_text(text, encoding="utf-8")
                print(f"[{ts}] {label} Successfully processed via {model_used}.")

                if uploaded_file.name:
                    client.files.delete(name=uploaded_file.name)
                time.sleep(2)
    finally:
        doc.close()

    # Merge cached chunks in order
    all_chunks = [
        f.read_text(encoding="utf-8") for f in (chunk_file_for(cache_dir, s, e) for s, e in chunk_ranges) if f.exists()
    ]
    output_path.write_text("\n\n---\n\n".join(all_chunks), encoding="utf-8")
    print(f"\nAll pages assembled! Saved to: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract PDF rules via Gemini Vision with automated model failover.")
    parser.add_argument("input_path", type=clean_path, help="Path to input PDF file or directory containing PDFs")
    parser.add_argument(
        "-o",
        "--output",
        type=clean_path,
        default=None,
        help="Output directory, or a .md file path (defaults to next to the PDF)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8,
        help="Number of pages per processing chunk (default: 8)",
    )
    parser.add_argument(
        "--strategy",
        choices=["quality", "quota"],
        default="quality",
        help="Model cascade strategy: 'quality' prefers highest-capability Flash models; "
        "'quota' prefers highest-rate-limit Flash-Lite models (default: quality).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Explicit Gemini model to use instead of dynamic discovery (e.g. gemini-3.8-flash).",
    )
    args = parser.parse_args()

    if not args.input_path.exists():
        sys.exit(f"Error: Path does not exist: {args.input_path}")

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

    targets = [(pdf, resolve_md_output(args.output, default_dir, pdf.stem, GEMINI_TAG)) for pdf in pdf_files]
    print(f"Found {len(pdf_files)} PDF(s) to process. Output target: {targets[0][1].parent}\n")

    model_pool = [args.model] if args.model else None

    for idx, (pdf_path, out_file) in enumerate(targets, 1):
        print(f"[{idx}/{len(targets)}] Extracting via Gemini: {pdf_path.name}...")
        try:
            extract_pdf(
                pdf_path,
                out_file,
                chunk_size=args.chunk_size,
                model_pool=model_pool,
                strategy=args.strategy,
            )
        except Exception as e:  # noqa: BLE001
            print(f"       -> Failed to process {pdf_path.name}: {e}", file=sys.stderr)

    print("\nGemini processing complete.")


if __name__ == "__main__":
    main()
