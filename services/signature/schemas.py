from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExtractRequest(BaseModel):
    """Request body for /extract — a non-empty list of image URLs / base64 payloads."""

    images: list[str] = Field(..., min_length=1, description="List of image URLs or base64 payloads")


class Signature(BaseModel):
    """One detected signature: which image, the text, where it is, how confident."""

    image_index: int = Field(..., ge=0)
    signature_text: str = Field(..., min_length=1)
    location_hint: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("signature_text", "location_hint")
    @classmethod
    def _strip(cls, v: str) -> str:
        """Trim surrounding whitespace from text fields."""
        return v.strip()


class ExtractResponse(BaseModel):
    """Task 2 output: one flat list of signatures across all submitted images."""

    signatures: list[Signature]


class TextRegion(BaseModel):
    """A pass-1 candidate text region: raw text, location, and visual appearance."""

    text: str
    location: str
    appearance: str
