"""Independent cross-check of the 20-Nov-2026 AN official PDFs. Deliberately shares NO code with app.vsb_alloc / app.regno:
it re-derives every figure from the raw page text with its own small regex logic, so the app parser can be compared to it.

Input: the text layer of each page (fixtures in real_20nov26/, '\\f' between pages).  Limits: this is the text layer only; seat
positions are taken from text order (a seat number immediately followed by a register number), validated against the 4-column
serpentine numbering printed on every sheet.
"""
import re
from collections import Counter, defaultdict
from pathlib import Path

FIX = Path(__file__).parent / "real_20nov26"
REG = re.compile(r"(?<!\d)\d{12}(?!\d)")


def pages(name):
    return [p for p in (FIX / name).read_text().split("\f") if p.strip()]


def expand_short_list(text):
    """'922523105015, 017, 021 ... 922525114001 - 005, 301 - 303' -> full numbers (own implementation)."""
    toks = re.findall(r"\d+|-", text)
    out, prefix, i = [], None, 0

    def full(t):
        nonlocal prefix
        if len(t) == 12:
            prefix = t[:9]
            return t
        assert len(t) == 3 and prefix, f"cannot expand {t!r}"
        return prefix + t

    while i < len(toks):
        if i + 2 < len(toks) and toks[i + 1] == "-":
            a, b = full(toks[i]), full(toks[i + 2])
            out += [str(n) for n in range(int(a), int(b) + 1)]
            i += 3
        else:
            out.append(full(toks[i]))
            i += 1
    return out


def hall_pdf():
    """-> blocks [(page, programme, code, hall, declared, [regs])], programme_totals {programme: declared}"""
    blocks, ptotals = [], {}
    for pno, text in enumerate(pages("20.11.26-AN-HALL.pages.txt"), 1):
        code, buf, pending = None, [], []
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for ln in lines:
            m = re.match(r"^\[([A-Z0-9]+)\]\s+(.*)$", ln)
            if m:
                code = m.group(1)
                continue
            m = re.match(r"^TOTAL (\d+)$", ln)
            if m:
                ptotals[prog] = int(m.group(1))
                continue
            if re.match(r"^(BE-|B\.TECH\.)", ln):
                prog = ln
                for b in pending:
                    b[1] = prog
                pending = []
                continue
            if re.match(r"^(V\.S\.B|\(An Auto|Approved|NH-67|OFFICE|HALL SEATING|DATE OF|Programme List|Hall Number|Powered)", ln):
                continue
            buf.append(ln)
            joined = " ".join(buf)
            m = re.search(r"(MB III [A-Z]?\d+) (\d+)$", joined)
            if m:
                regs = REG.findall(joined[:m.start()])
                b = [pno, None, code, m.group(1), int(m.group(2)), regs]
                blocks.append(b)
                pending.append(b)
                buf = []
    return [tuple(b) for b in blocks], ptotals


def seat_pdf():
    """-> sheets {hall: {'page', 'grid': {reg: seat}, 'empty': [seats], 'declared': int, 'subject_totals': {code: n},
                         'table_regs': [regs], 'table_declared_sum': int}}"""
    sheets = {}
    for pno, text in enumerate(pages("20.11.26-AN-SEAT.pages.txt"), 1):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        hall = re.search(r"EXAM HALL : (MB III [A-Z]?\d+)", text).group(1)
        h_i = next(i for i, l in enumerate(lines) if l.startswith("EXAM HALL"))
        t_i = next(i for i, l in enumerate(lines) if re.match(r"^CODE TITLE OF THE PAPER", l))
        grid, empty, rows = {}, [], []
        for ln in lines[h_i + 1:t_i]:
            toks = ln.split()
            rows.append([t for t in toks if len(t) <= 2])
            for k, t in enumerate(toks):
                if len(t) == 12:
                    assert k > 0 and len(toks[k - 1]) <= 2, f"{hall}: register without seat label in {ln!r}"
                    grid[t] = int(toks[k - 1])
            used = {int(toks[k - 1]) for k, t in enumerate(toks) if len(t) == 12}
            empty += [int(t) for t in toks if len(t) <= 2 and int(t) not in used]
        body = lines[t_i + 1:]
        declared = int(next(l for l in body if l.startswith("TOTAL ")).split()[1])
        table_text = " ".join(l for l in body if not l.startswith("TOTAL ") and not l.startswith("Powered"))
        # subject totals: "<CODE> <TITLE...> <n>" -- the code is 2 digits + 3 letters + 3 digits; the number after the title
        sub_tot = {}
        for m in re.finditer(r"(\d{2}[A-Z]{3}\d{3}) ([A-Z ()&.,\-]+?) (\d{1,2})(?= \d{12}| \d{2}[A-Z]{3}\d{3}|$|\s*CIRCUITS|\s)", table_text):
            pass
        for ln in body:
            m = re.match(r"^(\d{2}[A-Z]{3}\d{3}) (.*?) (\d{1,2})(?: (\d{12}.*))?$", ln)
            if m and not ln.startswith("TOTAL"):
                sub_tot[m.group(1)] = int(m.group(3))
        # the register part of the table = every digit/comma/dash run that is not a code, a title or a total
        reg_text = " ".join(
            (re.match(r"^\d{2}[A-Z]{3}\d{3} .*? \d{1,2} (.*)$", l).group(1) if re.match(r"^\d{2}[A-Z]{3}\d{3} .*? \d{1,2} \d{12}", l) else
             "" if re.match(r"^\d{2}[A-Z]{3}\d{3} ", l) or l.startswith("TOTAL") or l.startswith("Powered") or not re.search(r"\d", l) else l)
            for l in body)
        sheets[hall] = {"page": pno, "grid": grid, "empty": sorted(set(empty)), "declared": declared, "subject_totals": sub_tot,
                        "table_regs": expand_short_list(reg_text), "rows": rows}
    return sheets


def serpentine_ok(rows):
    """Every printed row must carry exactly the seat numbers r, 15-r, 14+r, 29-r of a 4-column x 7-row serpentine grid."""
    return [r for r in rows] == [[str(n) for n in (i, 15 - i, 14 + i, 29 - i)] for i in range(1, 8)]


def report():
    blocks, ptotals = hall_pdf()
    sheets = seat_pdf()
    hall_regs = [r for b in blocks for r in b[5]]
    out = {
        "hall_pdf_pages": len(pages("20.11.26-AN-HALL.pages.txt")), "seat_pdf_pages": len(pages("20.11.26-AN-SEAT.pages.txt")),
        "hall_blocks": len(blocks), "hall_register_occurrences": len(hall_regs), "hall_unique": len(set(hall_regs)),
        "hall_duplicates": sorted(r for r, n in Counter(hall_regs).items() if n > 1),
        "programme_totals": ptotals, "programme_totals_sum": sum(ptotals.values()),
        "programme_extracted": {p: sum(len(b[5]) for b in blocks if b[1] == p) for p in ptotals},
        "block_count_mismatch": [(b[3], b[2], b[4], len(b[5])) for b in blocks if b[4] != len(b[5])],
        "hall_totals": dict(sorted({h: sum(len(b[5]) for b in blocks if b[3] == h) for h in {b[3] for b in blocks}}.items())),
    }
    grid_regs = [r for s in sheets.values() for r in s["grid"]]
    out |= {
        "seat_sheets": len(sheets), "seat_grid_occurrences": len(grid_regs), "seat_unique": len(set(grid_regs)),
        "seat_duplicates": sorted(r for r, n in Counter(grid_regs).items() if n > 1),
        "seat_hall_totals": {h: len(s["grid"]) for h, s in sorted(sheets.items())},
        "seat_declared_vs_grid": [(h, s["declared"], len(s["grid"])) for h, s in sheets.items() if s["declared"] != len(s["grid"])],
        "serpentine_layout_ok": all(serpentine_ok(s["rows"]) for s in sheets.values()),
        "seat_duplicate_seats": [(h, [n for n, c in Counter(s["grid"].values()).items() if c > 1]) for h, s in sheets.items()
                                 if len(set(s["grid"].values())) != len(s["grid"])],
        "table_vs_grid_mismatch": [(h, sorted(set(s["table_regs"]) ^ set(s["grid"]))) for h, s in sheets.items()
                                   if set(s["table_regs"]) != set(s["grid"])],
    }
    # hall PDF vs seat PDF, per student
    hall_of = {r: b[3] for b in blocks for r in b[5]}
    seat_hall = {r: h for h, s in sheets.items() for r in s["grid"]}
    out |= {
        "only_on_hall_pdf": sorted(set(hall_of) - set(seat_hall)), "only_on_seat_pdf": sorted(set(seat_hall) - set(hall_of)),
        "hall_disagreements": sorted(r for r in hall_of if r in seat_hall and hall_of[r] != seat_hall[r]),
        "halls_only_on_hall_pdf": sorted({b[3] for b in blocks} - set(sheets)), "halls_only_on_seat_pdf": sorted(set(sheets) - {b[3] for b in blocks}),
    }
    # per (hall, subject): hall PDF block count vs seat-sheet printed subject total
    # (the same subject, e.g. 23CST402, is printed once per programme, so blocks are summed per (hall, subject) first)
    per = Counter()
    for b in blocks:
        per[(b[3], b[2])] += len(b[5])
    out["subject_hall_count_mismatch"] = [(h, c, n, sheets[h]["subject_totals"].get(c)) for (h, c), n in sorted(per.items())
                                          if sheets[h]["subject_totals"].get(c) != n]
    out["subject_hall_pairs_checked"] = len(per)
    out["assignments"] = {r: (seat_hall[r], sheets[seat_hall[r]]["grid"][r]) for r in seat_hall}
    out["subject_of"] = {r: b[2] for b in blocks for r in b[5]}
    out["programme_of"] = {r: b[1] for b in blocks for r in b[5]}
    out["page_of_hall"] = {r: b[0] for b in blocks for r in b[5]}
    out["page_of_seat"] = {r: sheets[h]["page"] for r, h in seat_hall.items()}
    return out


if __name__ == "__main__":
    import json
    rep = report()
    for k in ("assignments", "subject_of", "programme_of", "page_of_hall", "page_of_seat"):
        rep[k] = f"<{len(rep[k])} entries>"
    print(json.dumps(rep, indent=1, default=str))
