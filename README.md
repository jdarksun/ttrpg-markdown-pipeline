# ttrpg-markdown-pipeline

A hybrid PDF extraction and Open Knowledge Format (OKF) pipeline designed to convert complex tabletop RPG rulebooks (optimized for the **Cosmere RPG** and adaptable to any game system) into structured Markdown and semantic knowledge vaults.

---

## Why a Hybrid OKF Pipeline?

Tabletop RPG rulebooks present unique challenges for automated document extraction:
- **Standard OCR / Document AI** (like Docling) excels at reading columns, sidebars, tables, and long-form narrative text without hallucinations, but often fails on proprietary icon fonts (e.g. action diamonds `◆`, reaction arrows `↻`, or plot die symbols) or drops activation costs entirely.
- **Multimodal LLMs** (like Gemini Vision) accurately identify custom visual icons, talent headers, and action costs, but running entire books through vision models is slow, expensive, prone to small text omissions, and constrained by daily API quotas.

**This pipeline bridges both using the Open Knowledge Format (OKF):**
1. **Docling** extracts complete textual content, tables, and sidebars as the ground truth.
2. **Async Gemini Vision (`api.py`)** concurrently scans mechanics sections and outputs strict JSON objects conforming to typed Pydantic models (`OKFTalent`, `OKFWeapon`, `OKFRule`, etc.).
3. **OKF Shredder (`shredder.py`)** correlates Docling layout chunks with Gemini's JSON metadata, applies universal symbol repairs, and emits atomic Markdown files with YAML frontmatter.
4. **OKF Cross-Linker (`linker.py`)** builds a concept graph of the entire vault and hyper-links concept mentions across rule definitions.
5. **NotebookLM Bundler (`bundler.py`)** compiles category bundles (e.g. `Mistborn_All_Talents.md`) with preserved frontmatter for high-accuracy RAG and notebook ingestion.

---

## Installation

### Prerequisites
- Python 3.11 or newer
- A Google Gemini API key (set in your environment as `GEMINI_API_KEY` or in a `.env` file)

```bash
# Clone the repository
git clone https://github.com/your-username/ttrpg-markdown-pipeline.git
cd ttrpg-markdown-pipeline

# Install in editable mode
pip install -e .
```

---

## Quickstart: The Full Pipeline

Run the orchestrator on any unsplit master rulebook PDF:

```bash
ttrpg-pipeline "path/to/rulebook.pdf" -s "Cosmere RPG"
```

By default, this will create an `Extracted_Rulebook/` folder next to your PDF containing:
- `PDF_Chapters/`: Sliced chapter PDFs based on the book's Table of Contents.
- `Markdown/`: Verbatim Docling extracted Markdown files for each chapter.
- `okf_vault/`: Atomic concept Markdown files organized by `{sourcebook}/{type}s/` with YAML frontmatter and cross-links.
- `bundles/`: Consolidated category Markdown files ready for NotebookLM upload.

### Orchestrator Options

```bash
ttrpg-pipeline "path/to/rulebook.pdf" [OPTIONS]
```

| Option | Description |
|---|---|
| `-o`, `--output <DIR>` | Custom root output directory (defaults to `<pdf_dir>/Extracted_Rulebook`). |
| `-s`, `--sourcebook <NAME>` | Sourcebook name for OKF concept namespacing (default: `Cosmere RPG`). |
| `-f`, `--force` | Force re-extraction and overwrite existing cached chunks and outputs. |
| `--docling-only` | Bypass Gemini Vision and OKF shredding (useful if offline or out of quota). |
| `--chunk-size <INT>` | Number of pages per Gemini Vision batch (default: `8`). |
| `--strategy {quality,quota}` | Model cascade strategy: `quality` (Flash) or `quota` (Flash-Lite). |
| `--concurrency <INT>` | Maximum concurrent async chunk requests to Gemini API (default: `2`). |

### How the Orchestrator Routes Chapters

The orchestrator inspects each chapter title in the Table of Contents:
- **Mechanics Chapters** (containing keywords like `path`, `art`, `combat`, `item`, `adversar`):
  Runs Docling $\rightarrow$ Async Gemini Vision $\rightarrow$ OKF Shredder $\rightarrow$ Cross-Linker $\rightarrow$ Bundler.
- **Narrative / Lore Chapters**:
  Runs Docling $\rightarrow$ Glyph Patch. Output: `<Chapter> - DOCLING.md`.

---

## Standalone CLI Tools

Individual stages of the pipeline can also be run standalone:

### 1. `ttrpg-docling`
Batch or single-file conversion via Docling with layout analysis:
```bash
# Convert a single PDF
ttrpg-docling "Chapter_01.pdf" -o "Markdown/"

# Batch convert a folder of PDFs (skips already converted files)
ttrpg-docling "PDF_Chapters/" -o "Markdown/" --force
```

### 2. `ttrpg-gemini`
Vision-based rules extraction with automatic model failover and chunk caching:
```bash
# Extract a single PDF
ttrpg-gemini "04-Heroic_Paths.pdf" -o "Markdown/" --chunk-size 8

# Batch extract a folder of PDFs
ttrpg-gemini "PDF_Chapters/" -o "Markdown/"
```
*Note: If an API quota error occurs midway, progress is saved in `.cache_<output_stem>/`. Re-running the command resumes where it stopped.*

### 3. `ttrpg-patch`
Applies universal regex fixes, icon translations, and heading cleanup to any Markdown file or directory:
```bash
# Patch a single file
ttrpg-patch "Markdown/04-Heroic_Paths - DOCLING.md"

# Patch all final files in a directory
ttrpg-patch "Markdown/"
```

### 4. `ttrpg-glyphs`
Diagnostic utility for discovering Private Use Area (PUA) Unicode characters and icon fonts in a source PDF:
```bash
ttrpg-glyphs "rulebook.pdf" --search "Actions ("
```

---

## OKF Concept Structure

Atomic concept markdown files in `okf_vault/` feature structured YAML frontmatter:

```markdown
---
schema_version: 1.0.0
type: talent
sourcebook: Mistborn World Guide
name: Steel Bubble
category: Steel Allomancy
prerequisites: Steel 2+
activation: '[2 Actions]'
---

You create a protective bubble of repelling force around yourself. Any incoming metal projectiles...
```

---

## Project Architecture

```
src/ttrpg_markdown_pipeline/
├── __init__.py
├── common.py                 # Central path resolution and tag constants
├── models.py                 # Pydantic OKF concepts and YAML frontmatter serialization
├── orchestrator.py           # Pipeline master workflow and TOC-based PDF splitter
│
├── extractors/               # PDF -> Markdown / Vision extraction backends
│   ├── api.py                # Async Gemini Vision extractor with concurrent batching
│   ├── docling.py            # Docling OCR and layout analysis
│   ├── gemini.py             # CLI wrapper & sync Gemini Vision extractor
│   └── pymupdf.py            # PyMuPDF quick layout extractor
│
├── processors/               # Markdown & OKF post-processing engines
│   ├── bundler.py            # NotebookLM category bundler
│   ├── linker.py             # Vault-wide Markdown concept graph generator
│   ├── patch.py              # Generic icon, glyph, and regex repair runner
│   └── shredder.py           # Correlates Docling text with Gemini OKF JSON metadata
│
├── rules/                    # Game system configurations and prompts
│   └── cosmere.py            # Prompts, keywords, and universal inline icon fixes
│
└── tools/                    # PDF inspection and diagnostics
    └── inspect_glyphs.py     # Scans PDFs for Private Use Area glyphs and icon fonts
```

---

## Development & Code Quality

Linting, formatting, and strict type checking are configured in `pyproject.toml`:

```bash
# Run Ruff linter
ruff check

# Run Ruff formatter
ruff format --check

# Run Mypy static type checker
mypy src

# Run Pytest suite
pytest
```
