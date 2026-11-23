"""One public-visibility policy for VSB allocation records (used by EVERY student-facing and public query).

Publication flags alone never make a record public. A record is shown to a student only when its verification
status allows it, and it is never presented as more verified than it is:

  FULLY_VERIFIED       -> hall and seat shown as confirmed (hall list and seat sheet both checked).
  HALL_LIST_CONFIRMED  -> hall shown, seat WITHHELD, labelled "seat not yet checked".
  UNRESOLVED           -> nothing shown; the record is preserved (with its approval/publication history) for admin review.

Legacy rows (published before verification statuses existed, migration 0014 -> UNRESOLVED) are therefore hidden from
students without being deleted, upgraded or rewritten.
"""
from __future__ import annotations

from sqlalchemy import and_

from .. import doc_models as dm

FULL = "FULLY_VERIFIED"
HALL_ONLY = "HALL_LIST_CONFIRMED"
UNRESOLVED = "UNRESOLVED"

VERIFICATION_LABELS = {
    FULL: "Verified against the official hall list and seat sheet.",
    HALL_ONLY: "Hall confirmed from the official hall list. The seat has not yet been checked against the seat sheet.",
}
UNAVAILABLE_NOTE = ("Allocations that have not been verified against the official documents are not shown. "
                    "Please check the official notice or ask the Controller of Examinations.")


def public_filter():
    """SQL condition: published + approved + a verification status that may be shown at all."""
    return and_(dm.VsbAllocRecord.published == True,  # noqa: E712
                dm.VsbAllocRecord.review_status == "approved",
                dm.VsbAllocRecord.verification_status.in_((FULL, HALL_ONLY)))


def seat_public_filter():
    """SQL condition for anything that reveals a SEAT (seat maps, taken-seat lists): fully verified only."""
    return and_(public_filter(), dm.VsbAllocRecord.verification_status == FULL)


def present(status: str | None, hall: str | None, seat: str | None) -> dict:
    """What a student may be told about one visible record."""
    if status == FULL:
        return {"hall": hall, "seat": seat, "verification_status": FULL, "verification_label": VERIFICATION_LABELS[FULL]}
    if status == HALL_ONLY:
        return {"hall": hall, "seat": None, "verification_status": HALL_ONLY, "verification_label": VERIFICATION_LABELS[HALL_ONLY]}
    return {}
