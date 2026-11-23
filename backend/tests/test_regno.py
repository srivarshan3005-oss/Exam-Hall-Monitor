import pytest
from app.regno import (normalize_register_number, is_standard_register_number, id_kind, expand_register_list,
                       compare_with_declared, MAX_RANGE_SPAN)


@pytest.mark.parametrize("raw,out", [("990025106001", "990025106001"), (" 9900 2510-6001 ", "990025106001"),
                                      ("26144691179", "26144691179"), ("ab12cd34", "AB12CD34")])
def test_normalize_ok(raw, out):
    assert normalize_register_number(raw) == out


@pytest.mark.parametrize("raw", ["", "12345", "9900251060!1", "x" * 21, None])
def test_normalize_rejects(raw):
    with pytest.raises(ValueError):
        normalize_register_number(raw)


def test_kinds():
    assert is_standard_register_number("990025106001") and id_kind("990025106001") == "standard12"
    assert id_kind("26144691179") == "nonstandard" and id_kind("A1234567") == "nonstandard"


def test_simple_compressed_list_and_range():
    r = expand_register_list("990025106006, 008, 042 - 045")
    assert r.numbers == ["990025106006", "990025106008", "990025106042", "990025106043", "990025106044", "990025106045"]
    assert r.clean and r.count == 6


def test_prefix_changes_with_each_full_number():
    r = expand_register_list("990025106293, 304, 990025114002, 004 - 006")
    assert r.numbers == ["990025106293", "990025106304", "990025114002", "990025114004", "990025114005", "990025114006"]


def test_wrapped_range_across_lines():
    r = expand_register_list("990025114002, 004 -\n005, 007")
    assert r.numbers == ["990025114002", "990025114004", "990025114005", "990025114007"] and r.clean


def test_range_between_full_numbers_and_dash_variants():
    assert expand_register_list("990025106001 – 990025106003").numbers == ["990025106001", "990025106002", "990025106003"]
    assert expand_register_list("990025106001—003").count == 3


def test_nonstandard_id_kept_verbatim_and_clears_prefix():
    r = expand_register_list("26144691179, 990025106005, 007")
    assert r.numbers == ["26144691179", "990025106005", "990025106007"]
    assert [i.kind for i in r.issues] == ["nonstandard_id"]
    r2 = expand_register_list("990025106005, 26144691179, 007")
    assert r2.numbers == ["990025106005", "26144691179"]           # '007' is NOT guessed
    assert {i.kind for i in r2.issues} == {"nonstandard_id", "ambiguous_prefix"}


def test_short_number_without_prefix_is_not_guessed():
    r = expand_register_list("008, 010")
    assert r.numbers == [] and [i.kind for i in r.issues] == ["ambiguous_prefix"] * 2


@pytest.mark.parametrize("text,kind", [("990025106010 - 005", "bad_range"), ("990025106010 -", "bad_range"),
                                       ("- 990025106010", "bad_range"), ("990025106001 - 990025107005", "bad_range"),
                                       ("%s - %s" % ("990025106001", "990025106999"), "range_too_wide")])
def test_bad_ranges_reported_not_expanded(text, kind):
    r = expand_register_list(text)
    assert kind in [i.kind for i in r.issues]
    assert r.count <= 1  # at most the start token itself; never a guessed span


def test_duplicates_reported():
    r = expand_register_list("990025106001, 001")
    assert r.numbers == ["990025106001"] and [i.kind for i in r.issues] == ["duplicate"]


def test_garbage_tokens_reported():
    r = expand_register_list("Total 25 990025106001")
    assert r.numbers == ["990025106001"] and any(i.kind == "unparsed_token" for i in r.issues)


def test_compare_with_declared():
    assert compare_with_declared(25, 25) == "ok" and compare_with_declared(24, 25) == "mismatch"
    assert compare_with_declared(5, None) == "unchecked"
    assert MAX_RANGE_SPAN >= 100
