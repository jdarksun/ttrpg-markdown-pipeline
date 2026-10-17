"""Rule definitions and game-specific post-processing logic."""

from ttrpg_markdown_pipeline.rules.cosmere import (
    DEFAULT_PROMPT,
    MECHANICS_KEYWORDS,
    UNIVERSAL_INLINE_FIXES,
    patch_cosmere_rules,
)

__all__ = [
    "DEFAULT_PROMPT",
    "MECHANICS_KEYWORDS",
    "UNIVERSAL_INLINE_FIXES",
    "patch_cosmere_rules",
]

