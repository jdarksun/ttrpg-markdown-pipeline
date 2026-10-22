"""Rule definitions and game-specific post-processing logic."""

from ttrpg_markdown_pipeline.rules.cosmere import (
    ADVENTURE_KEYWORDS,
    ADVENTURE_PROMPT,
    DEFAULT_PROMPT,
    LORE_KEYWORDS,
    LORE_PROMPT,
    MECHANICS_KEYWORDS,
    UNIVERSAL_INLINE_FIXES,
    patch_cosmere_rules,
)

__all__ = [
    "ADVENTURE_KEYWORDS",
    "ADVENTURE_PROMPT",
    "DEFAULT_PROMPT",
    "LORE_KEYWORDS",
    "LORE_PROMPT",
    "MECHANICS_KEYWORDS",
    "UNIVERSAL_INLINE_FIXES",
    "patch_cosmere_rules",
]
