import pytest
from pydantic import ValidationError

from services.artwork.schemas import ArtworkResult
from services.signature.schemas import Signature


def test_artwork_result_accepts_valid_payload():
    """ArtworkResult accepts a well-formed payload at the minimum keyword count."""
    res = ArtworkResult(
        keywords=["lithograph", "mysticism", "monochrome", "figure", "1970s"],
        caption="A robed mystical figure rendered in stark monochrome lithograph.",
        description=(
            "A central robed figure dominates the composition. The artist uses bold "
            "monochrome contrast typical of mid-20th-century lithography. The mood "
            "is enigmatic and ritualistic. Fine line work defines drapery and "
            "facial features."
        ),
    )
    assert len(res.keywords) == 5


def test_artwork_caption_word_limit():
    """ArtworkResult rejects a caption longer than 20 words per the brief."""
    with pytest.raises(ValidationError):
        ArtworkResult(
            keywords=["a", "b", "c", "d", "e"],
            caption=" ".join(["word"] * 25),
            description="Three sentences. Like this. And this.",
        )


def test_artwork_requires_min_keywords():
    """ArtworkResult rejects fewer than 5 keywords per the brief."""
    with pytest.raises(ValidationError):
        ArtworkResult(
            keywords=["one", "two"],
            caption="ok",
            description="ok ok ok.",
        )


def test_signature_clamps_confidence():
    """Signature rejects a confidence value outside the [0.0, 1.0] range."""
    with pytest.raises(ValidationError):
        Signature(image_index=0, signature_text="Guy Duc", location_hint="lower right", confidence=1.5)


def test_signature_strips_whitespace():
    """Signature trims surrounding whitespace from text fields."""
    s = Signature(image_index=0, signature_text="  Guy Duc  ", location_hint="  lower right  ", confidence=0.9)
    assert s.signature_text == "Guy Duc"
    assert s.location_hint == "lower right"
