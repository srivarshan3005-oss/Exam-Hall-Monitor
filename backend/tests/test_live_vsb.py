"""LIVE-SOURCE tests: these talk to the REAL official VSB websites. They are skipped unless VSB_LIVE_TESTS=1.

Everything else in the suite is FIXTURE-based and never touches the network. A pass here proves only what it asserts, on the day
it was run; a skip means "not verified live" - never "verified".

    VSB_LIVE_TESTS=1 python -m pytest tests/test_live_vsb.py -v -s
"""
import os

import pytest
from sqlalchemy import select

from app import doc_models as dm
from app.vsb_live import cycle

pytestmark = pytest.mark.skipif(os.environ.get("VSB_LIVE_TESTS") != "1", reason="live-source tests are opt-in (set VSB_LIVE_TESTS=1)")


def test_live_discovery_download_ingest_and_lookup(client, db):
    out = cycle.run_cycle(trigger="manual", actor="live-test")
    print("\nLIVE CYCLE:", out)
    health = db.scalars(select(dm.VsbSourceHealth)).all()
    for h in health:
        print(f"  {h.method:9} {h.last_status:7} items={h.items_found} http={h.last_http_status} {h.url[:80]} {h.last_error or ''}")
    assert any(h.last_status == "ok" for h in health), "no official source could be read"
    links = db.scalars(select(dm.VsbSourceLink)).all()
    print("  PDF links discovered:", len(links), "| allotment links:", sum(1 for l in links if l.doc_kind in ("hall_allotment", "seating_allotment")))
    assert links, "no PDF links were discovered"
    rows = db.scalars(select(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True).limit(1)).all()  # noqa: E712
    if not rows:
        pytest.skip("the official site currently lists no parsable hall/seating allotment PDF")
    reg = rows[0].register_number
    d = client.get(f"/api/public/lookup/{reg}").json()
    assert d["records"] and d["records"][0]["sources"]
    img = client.get(d["records"][0]["sources"][0]["image_url"])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    print("  looked up", reg[:6] + "******", "->", d["status"], len(d["records"]), "record(s); original page image OK")
