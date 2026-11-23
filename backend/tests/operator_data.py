"""Skip markers and source lookups for tests that need the ORIGINAL-PORTAL data held by the operator.

That data (allotments.json, provenance, corrections, seating-chart evidence and the hall-label review CSV) contains
real student register numbers and is therefore NOT part of the public release package. A test that needs it is
SKIPPED with the reason shown in the pytest summary; it is never silently passed, and its assertions are unchanged.

To run these tests, place your authorised copy as described in backend/data/original_portal/README.md. Real register
numbers are never written into source code: they are looked up from the operator's own files at test time.
"""
import json
import os
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_ORIGINAL = _BACKEND / "data" / "original_portal"
_SOURCE = Path(os.environ.get("ORIGINAL_ALLOTMENTS_JSON") or _ORIGINAL / "source" / "allotments.json")
_CORRECTIONS = _ORIGINAL / "provenance_corrections.json"
_REASON = ("operator-supplied original-portal data not present (not distributed in the public release; "
           "see backend/data/original_portal/README.md)")


def _requires(path: Path):
    return pytest.mark.skipif(not path.is_file(), reason=f"{_REASON}: {path.relative_to(_REPO).as_posix()}")


requires_allotments = _requires(_SOURCE)
requires_provenance = _requires(_ORIGINAL / "allocation_provenance.json")
requires_corrections = _requires(_CORRECTIONS)
requires_variant_review = _requires(_REPO / "docs" / "hall_label_variant_review.csv")


def requires_chart(name: str):
    return _requires(_ORIGINAL / "seating_charts" / name)


def _source_items():
    data = json.loads(_SOURCE.read_text(encoding="utf-8"))
    for value in (data.values() if isinstance(data, dict) else [data]):
        for item in ([value] if isinstance(value, dict) else value if isinstance(value, list) else []):
            if isinstance(item, dict) and "register_number" in item:
                yield item


def source_register(**match):
    """The register number of the single source item whose fields equal `match`. Fails if none or several match."""
    hits = {str(it["register_number"]) for it in _source_items()
            if all(str(it.get(k)) == str(v) for k, v in match.items())}
    assert len(hits) == 1, f"expected exactly one source register for {match}, found {len(hits)}"
    return hits.pop()


def correction_register(field: str):
    """The register number of the single hall/seat correction in the operator's corrections record for `field`."""
    records = json.loads(_CORRECTIONS.read_text(encoding="utf-8"))["corrections"]
    hits = {key.split("|")[0] for key, rec in records.items() if rec.get("field") == field}
    assert len(hits) == 1, f"expected exactly one '{field}' correction, found {len(hits)}"
    return hits.pop()
