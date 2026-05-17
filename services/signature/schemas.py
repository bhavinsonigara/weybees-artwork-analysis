from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExtractRequest(BaseModel):
    images: list[str] = Field(..., min_length=1, description="List of image URLs or base64 payloads")


class Signature(BaseModel):
    image_index: int = Field(..., ge=0)
    signature_text: str = Field(..., min_length=1)
    location_hint: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("signature_text", "location_hint")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ExtractResponse(BaseModel):
    signatures: list[Signature]


class TextRegion(BaseModel):
    text: str
    location: str
    appearance: str
