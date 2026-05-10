import pytest
from unittest.mock import patch, MagicMock
from langdetect import LangDetectException

from collect import distance, select_diverse, detect_language


# ---------------------------------------------------------------------------
# distance()
# ---------------------------------------------------------------------------

def make_video(id="v1", title="hello world test", category_id=None, language=None):
    return {"id": id, "title": title, "category_id": category_id, "language": language}


def test_distance_identical():
    v = make_video(category_id=10, language="en")
    assert distance(v, v) == 0.0


def test_distance_same_category_same_lang():
    a = make_video("a", "hello world foo", category_id=10, language="en")
    b = make_video("b", "hello world foo", category_id=10, language="en")
    assert distance(a, b) == 0.0


def test_distance_different_category_different_lang():
    a = make_video("a", "abc def ghi", category_id=10, language="en")
    b = make_video("b", "xyz uvw rst", category_id=20, language="ro")
    d = distance(a, b)
    assert d == pytest.approx(0.5 * 1.0 + 0.3 * 1.0 + 0.2 * 1.0)


def test_distance_both_category_none():
    a = make_video("a", "foo bar baz", category_id=None, language="en")
    b = make_video("b", "qux quux corge", category_id=None, language="fr")
    d = distance(a, b)
    # cat_dist=0.0 (both None), lang_dist=1.0, jaccard_dist=1.0
    assert d == pytest.approx(0.3 * 1.0 + 0.2 * 1.0)


def test_distance_one_category_none():
    a = make_video("a", "foo bar baz", category_id=None, language="en")
    b = make_video("b", "foo bar baz", category_id=10, language="en")
    d = distance(a, b)
    # cat_dist=0.0 (one None), lang_dist=0.0, jaccard_dist=0.0
    assert d == 0.0


# ---------------------------------------------------------------------------
# select_diverse()
# ---------------------------------------------------------------------------

def test_select_diverse_empty():
    assert select_diverse([]) == []


def test_select_diverse_fewer_than_n():
    candidates = [make_video("a"), make_video("b")]
    result = select_diverse(candidates, n=3)
    assert len(result) == 2


def test_select_diverse_exactly_n():
    candidates = [make_video("a"), make_video("b"), make_video("c")]
    result = select_diverse(candidates, n=3)
    assert len(result) == 3


def test_select_diverse_returns_n_distinct():
    candidates = [
        make_video("a", "cooking music food", category_id=26, language="en"),
        make_video("b", "sports game match", category_id=17, language="ro"),
        make_video("c", "film animation story", category_id=1, language="fr"),
        make_video("d", "cooking recipe kitchen", category_id=26, language="en"),
        make_video("e", "gaming play stream", category_id=20, language="de"),
    ]
    result = select_diverse(candidates, n=3)
    assert len(result) == 3
    ids = [v["id"] for v in result]
    assert len(ids) == len(set(ids)), "Duplicate IDs in result"


def test_select_diverse_deduplicates_by_id():
    # Same ID appears twice in candidates
    v = make_video("a", "hello world test")
    candidates = [v, v, make_video("b", "foo bar baz"), make_video("c", "xyz uvw rst")]
    result = select_diverse(candidates, n=3)
    ids = [v["id"] for v in result]
    assert ids.count("a") == 1


def test_select_diverse_all_identical():
    candidates = [make_video(str(i), "same title here", category_id=10, language="en") for i in range(5)]
    result = select_diverse(candidates, n=3)
    assert len(result) == 3
    ids = [v["id"] for v in result]
    assert len(set(ids)) == 3


# ---------------------------------------------------------------------------
# detect_language()
# ---------------------------------------------------------------------------

def test_detect_language_too_short():
    assert detect_language("OK") is None
    assert detect_language("two words") is None


def test_detect_language_empty():
    assert detect_language("") is None


def test_detect_language_low_confidence():
    mock_result = MagicMock()
    mock_result.prob = 0.5
    mock_result.lang = "en"
    with patch("collect.detect_langs", return_value=[mock_result]):
        assert detect_language("some title here") is None


def test_detect_language_exception():
    with patch("collect.detect_langs", side_effect=LangDetectException(0, "")):
        assert detect_language("some title here") is None


def test_detect_language_happy_path():
    mock_result = MagicMock()
    mock_result.prob = 0.95
    mock_result.lang = "ro"
    with patch("collect.detect_langs", return_value=[mock_result]):
        result = detect_language("un titlu in romana")
        assert result == "ro"
