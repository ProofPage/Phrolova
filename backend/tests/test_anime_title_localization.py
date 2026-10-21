"""Preserve identity when a title has no exact Korean mapping."""
import pytest

from app.api.lilac import _localize_title


@pytest.mark.parametrize("title", [
    "The Apothecary Diaries Season 99",
    "Blue Box: Unmapped Special",
    "Not Naruto",
    "apothecary",
    "",
])
def test_unmapped_titles_are_preserved(title):
    assert _localize_title(title) == title


@pytest.mark.parametrize(("title", "expected"), [
    ("The Apothecary Diaries", "약사의 혼잣말"),
    ("The Apothecary Diaries Season 3", "약사의 혼잣말 3기"),
    ("  BLUE BOX SEASON 2  ", "푸른 상자 2기"),
])
def test_exact_title_mapping(title, expected):
    assert _localize_title(title) == expected
