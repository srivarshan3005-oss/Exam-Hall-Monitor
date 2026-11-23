"""Seating-sheet fixtures.

REAL_TEXT_* : text layer of pages of the official 14.11.26-FN-SEAT.pdf (fetched 15 Nov 2026), register numbers rewritten
              92252x -> 92259x (see fixtures_hall.py). They exercise the text-order fallback and the table-row logic.
build_page  : synthetic page generator that reproduces the printed geometry (4 serpentine columns, 7 rows) and emits BOTH the
              stream-order text and word boxes, so the coordinate mapping can be tested - including empty cells whose seat
              number is printed without a register number, dropped labels and duplicated labels.
write_pdf   : draws a generated page with reportlab so real PDF coordinates can be read back (pdfplumber in tests, PyMuPDF in
              production).
"""
from app.vsb_alloc.common import PageInput, Word

PAGE_HEAD = """V.S.B. ENGINEERING COLLEGE
(An Autonomous Institution)
Approved by AICTE, Affiliated to Anna University, Chennai.
NH-67 Covai Road, Karudayampalayam Post, Karur-639111.-
HALL SEATING FOR THE END SEMESTER EXAMINATIONS - DEC 2026
DATE OF EXAMINATION: 14-11-2026 SESSION : FN
"""
TABLE_HEAD = "CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS\n"

# ----- verbatim-structure pages (text layer) -----
REAL_TEXT_02 = PAGE_HEAD + """EXAM HALL : MB III 02 Name of the Hall Superindentent : 
1 14 15 28 994177572013
2 994177572001 13 992829432006 16 994177572007 27 992829432012
3 992829432001 12 994177572006 17 992829432007 26 994177572012
4 994177572002 11 992829432005 18 994177572008 25 992829432011
5 992829432002 10 994177572005 19 992829432008 24 994177572011
6 994177572003 9 992829432004 20 994177572009 23 992829432010
7 992829432003 8 994177572004 21 992829432009 22 994177572010
""" + TABLE_HEAD + """23CST302R FOUNDATIONS OF DATA SCIENCE 13 994177572001 - 013
23EET302R ELECTRICAL MACHINES - I 12 992829432001 - 012
TOTAL 25
"""

REAL_TEXT_103 = PAGE_HEAD + """EXAM HALL : MB III 103 Name of the Hall Superindentent : 
1 14 15 28 994177572078
2 994177572066 13 999719394002 16 994177572072 27 999719394008
3 992829432063 12 994177572071 17 999719394003 26 994177572077
4 994177572067 11 999719394001 18 994177572073 25 999719394007
5 992829432301 10 994177572070 19 999719394004 24 994177572076
6 994177572068 9 992829432501 20 994177572074 23 999719394006
7 992829432302 8 994177572069 21 999719394005 22 994177572075
""" + TABLE_HEAD + """23CST302R FOUNDATIONS OF DATA SCIENCE 13 994177572066 - 078
23CBT303 FORMAL LANGUAGE AND AUTOMATA THEORY 8 999719394001 - 008
23EET302R ELECTRICAL MACHINES - I 4 992829432063, 301 - 302, 501
TOTAL 25
"""

REAL_TEXT_208 = PAGE_HEAD + """EXAM HALL : MB III 208 Name of the Hall Superindentent : 
1 14 15 28 994630560003
2 994177572186 13 992332477016 16 994177572301 27 992332477022
3 992332477011 12 994177572193 17 992332477017 26 994630560002
4 994177572187 11 992332477015 18 994177572302 25 992332477021
5 992332477012 10 994177572192 19 992332477018 24 994630560001
6 994177572188 9 992332477014 20 994177572303 23 992332477020
7 992332477013 8 994177572189 21 992332477019 22 994177572304
""" + TABLE_HEAD + """23BMT302 SENSORS AND MEASUREMENTS 3 994630560001 - 003
23CST302R FOUNDATIONS OF DATA SCIENCE 22 994177572186 - 189, 192 - 193, 301 - 304, 992332477011 - 022
TOTAL 25
"""

# register lines are printed BEFORE the "CODE TITLE TOTAL" line of the second subject
REAL_TEXT_A203 = PAGE_HEAD + """EXAM HALL : MB III A203 Name of the Hall Superindentent : 
1 14 15 28 995563233126
2 995563233114 13 990930217183 16 995563233120 27 997333511007
3 990162938032 12 995563233119 17 990930217302 26 995563233125
4 995563233115 11 990930217163 18 995563233121 25 995430424062
5 990162938306 10 995563233118 19 995430424008 24 995563233124
6 995563233116 9 990930217159 20 995563233122 23 995430424030
7 990930217158 8 995563233117 21 995430424026 22 995563233123
""" + TABLE_HEAD + """23CST302R FOUNDATIONS OF DATA SCIENCE 13 995563233114 - 126
990162938032, 306, 995430424008, 026, 030, 062, 997333511007,
990930217158 - 159, 163, 183, 302
23GET401R ENVIRONMENTAL SCIENCE AND ENGINEERING 12
TOTAL 25
"""

# the anomalous real page: some seat numbers are missing/duplicated in the text layer, a whole row (6) has no labels
REAL_TEXT_A204 = PAGE_HEAD + """EXAM HALL : MB III A204 Name of the Hall Superindentent : 
1 14 15 28 992152626012
2 995563233127 27 16 27
3 997333511111 12 997333511182 17 997510640060 26 997721393004
4 995563233301 25 18 25
5 997333511116 10 999038632023 19 997721393016 24 991152918026
7 995563233302 8 994767654014 21 999057106020 22 997721393014
""" + TABLE_HEAD + """23CET304 WATER SUPPLY AND WASTEWATER ENGINEERING 2 992152626012, 997721393004
23CST302R FOUNDATIONS OF DATA SCIENCE 3 995563233127, 301 - 302
997721393014, 016, 994767654014, 999057106020, 997510640060,
997333511111, 116, 182, 991152918026, 999038632023
23GET401R 10 ENVIRONMENTAL SCIENCE AND ENGINEERING
TOTAL 15
"""

# ----- synthetic generator -----
LABEL_X = [40.0, 170.0, 300.0, 430.0]
ROW_Y0, ROW_DY = 150.0, 18.0
SEAT_OF = [lambda r: 1 + r, lambda r: 14 - r, lambda r: 15 + r, lambda r: 28 - r]     # serpentine, rows 0..6


def seat_cell(seat: int):
    for c, f in enumerate(SEAT_OF):
        for r in range(7):
            if f(r) == seat:
                return r, c
    raise ValueError(seat)


def build_page(index, hall, seats, subjects, *, date="14-11-2026", session="FN", total=None, pre_lines=(),
               drop_labels=(), extra_labels=(), with_words=True, table_total_override=None):
    """seats: {seat_no: register_number}. subjects: [(code, title, total, register_text)].
    pre_lines: codes whose register text is printed on lines BEFORE the code line (vertically centred cell).
    drop_labels: [(row, col)] cells whose seat number is NOT printed. extra_labels: [(row, col, number)] stray labels."""
    words: list[Word] = []
    text = PAGE_HEAD.replace("14-11-2026", date).replace("SESSION : FN", f"SESSION : {session}")
    text += f"EXAM HALL : {hall} Name of the Hall Superindentent : \n"
    y = 100.0
    for t, x in (("EXAM", 40), ("HALL", 80), (":", 110), (hall, 120), ("Name", 250), ("of", 280), ("the", 295), ("Hall", 315),
                 ("Superindentent", 340), (":", 420)):
        words.append(Word(t, x, y, x + 6 * len(t), y + 9))
    drop = set(drop_labels)
    extra: dict = {}
    for r, c, n in extra_labels:
        extra.setdefault((r, c), []).append(n)
    for r in range(7):
        yy = ROW_Y0 + ROW_DY * r
        toks = []
        for c in range(4):
            n = SEAT_OF[c](r)
            reg = seats.get(n)
            if (r, c) not in drop:
                toks.append(str(n))
                words.append(Word(str(n), LABEL_X[c], yy, LABEL_X[c] + 7 * len(str(n)), yy + 9))
            for n2 in extra.get((r, c), []):
                toks.append(str(n2))
                words.append(Word(str(n2), LABEL_X[c], yy, LABEL_X[c] + 7 * len(str(n2)), yy + 9))
            if reg:
                toks.append(reg)
                words.append(Word(reg, LABEL_X[c] + 26, yy, LABEL_X[c] + 26 + 6 * len(reg), yy + 9))
        if any(t for t in toks):
            text += " ".join(_group_empty(toks)) + "\n"
    ty = 300.0
    for t, x in (("CODE", 40), ("TITLE", 100), ("OF", 140), ("THE", 160), ("PAPER", 185), ("TOTAL", 300), ("REGISTER", 350), ("NUMBERS", 420)):
        words.append(Word(t, x, ty, x + 6 * len(t), ty + 9))
    text += TABLE_HEAD
    for code, title, tot, regs in subjects:
        if code in pre_lines:
            parts = [p.strip() for p in regs.split("\n")]
            text += "\n".join(parts) + "\n" + f"{code} {tot} {title}\n"
        else:
            text += f"{code} {title} {tot} {regs}\n"
    text += f"TOTAL {total if total is not None else len(seats)}\n" if table_total_override is None else f"TOTAL {table_total_override}\n"
    return PageInput(index, text, words if with_words else [], "text_layer")


def _group_empty(toks):
    return toks


def write_pdf(path, page: PageInput, height=842.0):
    """Draw the generated page's words with reportlab (text drawn in word order)."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(595.0, height))
    c.setFont("Helvetica", 8)
    for w in page.words:
        c.drawString(w.x0, height - w.y1 + 2, w.text)
    c.showPage()
    c.save()
