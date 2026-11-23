"""Register-number utilities shared by the API and the PDF pipeline (Phase 3).

VSB seating PDFs print 12-digit register numbers, but also
* compressed lists:  "992696352006, 008, 042 - 116"   (short tokens inherit the prefix)
* ranges that wrap across lines:  "004 -\\n005"
* occasional non-standard ids (e.g. an 11-digit number) that must be kept verbatim.
Nothing here guesses: anything ambiguous is reported as an issue and NOT expanded.
"""
import re
from dataclasses import dataclass, field

_CLEAN = re.compile(r"[\s\-_.\u00a0]+")
_VALID = re.compile(r"^[A-Z0-9]{6,20}$")
_STANDARD = re.compile(r"^\d{12}$")
MAX_RANGE_SPAN = 400  # a single "a - b" range wider than this is reported, not expanded


def normalize_register_number(raw: str) -> str:
    """Strip spaces/hyphens, upper-case. Raises ValueError if the result is not plausible."""
    value = _CLEAN.sub("", str(raw or "")).upper()
    if not _VALID.match(value):
        raise ValueError("Register number must be 6-20 letters/digits")
    return value


def is_standard_register_number(value: str) -> bool:
    return bool(_STANDARD.match(value))


def id_kind(value: str) -> str:
    return "standard12" if is_standard_register_number(value) else "nonstandard"


@dataclass
class ParseIssue:
    kind: str       # nonstandard_id | ambiguous_prefix | bad_range | range_too_wide | duplicate | unparsed_token
    token: str
    message: str


@dataclass
class ExpandResult:
    numbers: list[str] = field(default_factory=list)   # in printed order, duplicates removed
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.numbers)

    @property
    def clean(self) -> bool:
        return not self.issues


_TOKEN = re.compile(r"[A-Za-z0-9]+|-|–|—|,")
_RANGE_MARKS = ("-", "–", "—")
_SUFFIX_WIDTH = 3


def expand_register_list(text: str) -> ExpandResult:
    """Expand a printed register list into individual numbers.

    Rules: a 12-digit token sets the current 9-digit prefix; a 3-digit token inherits it;
    "A - B" is an inclusive range (A or B may be 3-digit). Anything else is kept verbatim
    as a non-standard id (and clears the prefix) or reported as an issue.
    """
    res = ExpandResult()
    seen: set[str] = set()
    prefix: str | None = None

    def add(num: str, token: str) -> None:
        if num in seen:
            res.issues.append(ParseIssue("duplicate", token, f"{num} appears more than once"))
            return
        seen.add(num)
        res.numbers.append(num)

    def resolve(tok: str, ctx_prefix: str | None) -> tuple[str | None, str | None]:
        """Return (full_number, new_prefix) or (None, prefix) if it cannot be resolved."""
        if re.fullmatch(r"\d{12}", tok):
            return tok, tok[:-_SUFFIX_WIDTH]
        if re.fullmatch(r"\d{%d}" % _SUFFIX_WIDTH, tok) and ctx_prefix:
            return ctx_prefix + tok, ctx_prefix
        return None, ctx_prefix

    tokens = [t for t in _TOKEN.findall(text.replace("\n", " ")) if t != ","]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _RANGE_MARKS:
            res.issues.append(ParseIssue("bad_range", tok, "Range marker without a start value"))
            i += 1
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        is_range = False
        if nxt in _RANGE_MARKS:
            if i + 2 < len(tokens) and tokens[i + 2] not in _RANGE_MARKS:
                is_range = True
            else:
                res.issues.append(ParseIssue("bad_range", tok, "Range marker without an end value"))
                i += 2
                continue

        if is_range:
            end_tok = tokens[i + 2]
            a, prefix_a = resolve(tok, prefix)
            b, _ = resolve(end_tok, prefix_a)
            label = f"{tok} - {end_tok}"
            if a is None or b is None:
                res.issues.append(ParseIssue("ambiguous_prefix", label,
                                             "Range endpoint has no usable 9-digit prefix; not expanded"))
            elif a[:-_SUFFIX_WIDTH] != b[:-_SUFFIX_WIDTH]:
                res.issues.append(ParseIssue("bad_range", label, "Range endpoints have different prefixes"))
            elif int(b) < int(a):
                res.issues.append(ParseIssue("bad_range", label, "Range end is smaller than its start"))
            elif int(b) - int(a) + 1 > MAX_RANGE_SPAN:
                res.issues.append(ParseIssue("range_too_wide", label, f"Range spans more than {MAX_RANGE_SPAN}"))
            else:
                for n in range(int(a), int(b) + 1):
                    add(str(n).zfill(12), label)
                prefix = a[:-_SUFFIX_WIDTH]
            i += 3
            continue

        full, new_prefix = resolve(tok, prefix)
        if full is not None:
            add(full, tok)
            prefix = new_prefix
        elif re.fullmatch(r"\d{3}", tok):
            res.issues.append(ParseIssue("ambiguous_prefix", tok,
                                         "Short number with no preceding 12-digit number; not expanded"))
        elif re.fullmatch(r"[A-Z0-9]{6,20}", tok.upper()) and any(c.isdigit() for c in tok):
            res.issues.append(ParseIssue("nonstandard_id", tok, "Non-standard identifier kept verbatim"))
            add(tok.upper(), tok)
            prefix = None  # a following short token would be ambiguous
        else:
            res.issues.append(ParseIssue("unparsed_token", tok, "Token is not a register number"))
        i += 1
    return res


def compare_with_declared(expanded_count: int, declared: int | None) -> str:
    """'ok' | 'mismatch' | 'unchecked' (no declared total printed)."""
    if declared is None:
        return "unchecked"
    return "ok" if expanded_count == declared else "mismatch"
