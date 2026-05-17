from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AnalyzeRequest(BaseModel):
    image: str = Field(..., description="Image URL (http/https) or base64-encoded payload")


class ArtworkResult(BaseModel):
    keywords: list[str] = Field(..., min_length=5, max_length=10)
    caption: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)

    @field_validator("keywords")
    @classmethod
    def _trim_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k and k.strip()]
        if not (5 <= len(cleaned) <= 10):
            raise ValueError("keywords must contain 5-10 non-empty tags")
        return cleaned

    @field_validator("caption")
    @classmethod
    def _caption_word_count(cls, v: str) -> str:
        if len(v.split()) > 20:
            raise ValueError("caption must be 20 words or fewer")
        return v.strip()
