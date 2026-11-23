"""A hall named identically by both official documents is shown even when the seat needs a check; any hall doubt hides it."""
from types import SimpleNamespace

from app.vsb_live import pipeline


def rec(h, s):
    return SimpleNamespace(hall_pdf_hall=h, seat_pdf_hall=s)


def test_agreed_hall_shown_when_documents_match():
    assert pipeline._agreed_hall(rec("MB III 308", "MB III 308"), ["seat_from_text_order"]) == "MB III 308"


def test_agreed_hall_hidden_when_documents_differ_or_missing():
    assert pipeline._agreed_hall(rec("MB III 308", "MB III 309"), []) is None
    assert pipeline._agreed_hall(rec("MB III 308", None), []) is None
    assert pipeline._agreed_hall(rec(None, None), []) is None


def test_agreed_hall_hidden_when_hall_is_doubted():
    assert pipeline._agreed_hall(rec("MB III 308", "MB III 308"), ["hall_label_variant"]) is None
    assert pipeline._agreed_hall(rec("MB III 308", "MB III 308"), ["source_documents_disagree"]) is None
