"""Open Knowledge Format (OKF) Pydantic Models for TTRPG rules, concepts, and mechanics."""

from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# Common action / activation standardizer
_ACTION_CANONICAL = {
    "1 action": "[1 Action]",
    "[1 action]": "[1 Action]",
    "2 actions": "[2 Actions]",
    "[2 actions]": "[2 Actions]",
    "3 actions": "[3 Actions]",
    "[3 actions]": "[3 Actions]",
    "reaction": "[Reaction]",
    "[reaction]": "[Reaction]",
    "free action": "[Free Action]",
    "[free action]": "[Free Action]",
    "special": "[Special Activation]",
    "special activation": "[Special Activation]",
    "[special activation]": "[Special Activation]",
    "passive": "[Passive]",
    "[passive]": "[Passive]",
    "always active": "[Passive]",
    "[always active]": "[Passive]",
}


def sanitize_activation(val: str | None) -> str | None:
    """Sanitizes and standardizes activation costs."""
    if not val:
        return val
    cleaned = val.strip()
    lower = cleaned.lower()
    return _ACTION_CANONICAL.get(lower, cleaned)


class OKFConcept(BaseModel):
    """Base class for all Open Knowledge Format concepts."""

    schema_version: str = Field(default="1.0.0", description="Semantic version of the OKF schema")
    type: str = Field(..., description="Concept type (e.g. talent, weapon, rule, ancestry, culture)")
    sourcebook: str = Field(..., description="Sourcebook or publication identifier (e.g. 'Mistborn World Guide')")
    name: str = Field(..., description="Canonical name of the concept")
    category: str = Field(..., description="Categorization or parent group (e.g. 'Steel Allomancy', 'Core Actions')")
    body_text: str = Field(default="", description="Markdown body text describing the concept mechanics")
    example_text: str | None = Field(
        default=None,
        description="Gameplay example or dialogue transcript illustrating the concept",
    )

    @field_validator("name", "category", "sourcebook", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    def to_markdown(self) -> str:
        """Serializes the model into a YAML frontmatter block followed by body_text and optional example_text."""
        data = self.model_dump(exclude={"body_text", "example_text"})
        # Clean YAML dump
        frontmatter = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).strip()
        body = self.body_text.strip()
        example = self.example_text.strip() if self.example_text else None

        parts = [f"---\n{frontmatter}\n---"]
        if body and example:
            parts.append(f"\n### Mechanics\n\n{body}")
            parts.append(f"\n### Example Play\n\n{example}\n")
        elif body:
            parts.append(f"\n{body}\n")
        elif example:
            parts.append(f"\n### Example Play\n\n{example}\n")
        else:
            parts.append("\n")

        return "\n".join(parts)


class OKFTalent(OKFConcept):
    """Represents a character talent, power, or feat."""

    type: Literal["talent"] = "talent"
    prerequisites: str | None = Field(default=None, description="Prerequisite conditions to take this talent")
    activation: str = Field(default="[Passive]", description="Action cost or activation mode")

    @field_validator("activation", mode="before")
    @classmethod
    def normalize_activation(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_activation(v)
        return v

    @field_validator("prerequisites", mode="before")
    @classmethod
    def clean_prereqs(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_clean = v.strip(" `*")
            return v_clean if v_clean and v_clean.lower() != "none" else None
        return v


class OKFWeapon(OKFConcept):
    """Represents a weapon or piece of armory."""

    type: Literal["weapon"] = "weapon"
    damage: str | None = Field(default=None, description="Damage formula or die code")
    range: str | None = Field(default=None, description="Effective range or category (e.g. Melee, 50/100 ft)")
    traits: list[str] = Field(default_factory=list, description="Weapon traits (e.g. Blast, Concealable)")
    cost: str | None = Field(default=None, description="Item cost or value")


class OKFArmor(OKFConcept):
    """Represents wearable armor or protective gear."""

    type: Literal["armor"] = "armor"
    deflect: str | int | None = Field(default=None, description="Deflection rating or armor defense")
    traits: list[str] = Field(default_factory=list, description="Armor traits (e.g. Cumbersome)")
    cost: str | None = Field(default=None, description="Item cost or value")


class OKFItem(OKFConcept):
    """Represents general equipment, gear, or consumable."""

    type: Literal["item"] = "item"
    cost: str | None = Field(default=None, description="Item cost or value")
    weight: str | None = Field(default=None, description="Item weight or bulk")


class OKFRule(OKFConcept):
    """Represents a core rule, condition, action, or subsystem."""

    type: Literal["rule"] = "rule"
    action_cost: str | None = Field(default=None, description="Action cost if this rule represents an action")
    trigger: str | None = Field(default=None, description="Trigger condition if reaction or interrupt")

    @field_validator("action_cost", mode="before")
    @classmethod
    def normalize_action_cost(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_activation(v)
        return v


class OKFAdversary(OKFConcept):
    """Represents a creature, NPC, or adversary statblock."""

    type: Literal["adversary"] = "adversary"
    tier: int | str | None = Field(default=None, description="Adversary tier or challenge rating")
    role: str | None = Field(default=None, description="Adversary role (e.g. Minion, Leader, Solo)")
