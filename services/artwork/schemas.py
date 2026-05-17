from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AnalyzeRequest(BaseModel):
    """Request body for /analyze — a single image URL or base64 payload."""

    image: str = Field(..., description="Image URL (http/https) or base64-encoded payload")


class ArtworkResult(BaseModel):
    """Task 1 output: 5-10 keywords, a one-line caption (<=20 words), and a 3-5 sentence description."""

    keywords: list[str] = Field(..., min_length=5, max_length=10)
    caption: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)

    @field_validator("keywords")
    @classmethod
    def _trim_keywords(cls, v: list[str]) -> list[str]:
        """Strip blanks and enforce the 5-10 non-empty tag count from the brief."""
        cleaned = [k.strip() for k in v if k and k.strip()]
        if not (5 <= len(cleaned) <= 10):
            raise ValueError("keywords must contain 5-10 non-empty tags")
        return cleaned

    @field_validator("caption")
    @classmethod
    def _caption_word_count(cls, v: str) -> str:
        """Enforce the brief's <=20 words constraint on the caption."""
        if len(v.split()) > 20:
            raise ValueError("caption must be 20 words or fewer")
        return v.strip()
