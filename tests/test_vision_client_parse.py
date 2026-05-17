from libs.vision_client import _extract_json


def test_extract_plain_json_object():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_inside_fence():
    text = "Here you go:\n```json\n{\"keywords\": [\"a\"], \"n\": 2}\n```\nThanks!"
    assert _extract_json(text) == {"keywords": ["a"], "n": 2}


def test_extract_array_with_surrounding_prose():
    text = "Result: [1, 2, 3]"
    assert _extract_json(text) == [1, 2, 3]
