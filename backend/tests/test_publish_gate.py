from scripts.publish_gate import publish_decision


def good_cycle():
    return {
        "status": "ok",
        "discovery": {"status": "ok", "links_found": 12},
        "ingest": {"parsed": 2, "failed": 0},
    }


def test_publish_gate_accepts_a_fully_successful_official_scan():
    assert publish_decision(good_cycle())[0] is True


def test_publish_gate_rejects_failed_official_scan_even_with_cached_links():
    cycle = good_cycle()
    cycle["status"] = "failed"
    cycle["discovery"]["status"] = "failed"
    assert publish_decision(cycle)[0] is False


def test_publish_gate_rejects_partial_scan():
    cycle = good_cycle()
    cycle["status"] = "partial"
    cycle["discovery"]["status"] = "partial"
    assert publish_decision(cycle)[0] is False


def test_publish_gate_rejects_empty_official_listing():
    cycle = good_cycle()
    cycle["discovery"]["links_found"] = 0
    assert publish_decision(cycle)[0] is False


def test_publish_gate_rejects_ingestion_crash_or_parse_failure():
    cycle = good_cycle()
    cycle["ingest_error"] = "ingestion crashed"
    assert publish_decision(cycle)[0] is False
    cycle = good_cycle()
    cycle["ingest"]["failed"] = 1
    assert publish_decision(cycle)[0] is False
