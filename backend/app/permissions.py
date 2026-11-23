"""Central role model.

Roles (stored in users.role):
  super_admin  Super administrator: everything an examination administrator can do, plus role assignment
               for administrators, administrator password resets and the security dashboard.
  admin        Examination administrator (the original Phase 1 "admin" role, unchanged).
  staff        Department staff. If users.department is set, student-level data is limited to that department.
  invigilator  Read-only: examination list, hall rosters and seating charts.
  student      Own record and own published results only.
"""
ROLES = ("super_admin", "admin", "staff", "invigilator", "student")
ROLE_LABELS = {"super_admin": "Super administrator", "admin": "Examination administrator",
               "staff": "Department staff", "invigilator": "Invigilator", "student": "Student"}
ADMIN_ROLES = ("super_admin", "admin")
STAFF_ROLES = ("super_admin", "admin", "staff")
READ_ROLES = ("super_admin", "admin", "staff", "invigilator")
RANK = {"student": 0, "invigilator": 1, "staff": 2, "admin": 3, "super_admin": 4}


def expand(roles: tuple[str, ...]) -> set[str]:
    """super_admin is implicitly allowed wherever 'admin' is."""
    out = set(roles)
    if "admin" in out:
        out.add("super_admin")
    return out


def can_assign(actor_role: str, target_role: str, current_role: str | None = None, legacy: bool = False) -> bool:
    """Only a super administrator may grant or remove administrator-level roles.
    legacy=True (no active super administrator exists yet) keeps the Phase 1 behaviour for 'admin'
    so an upgraded installation can never lock itself out; it ends once a super administrator exists."""
    if actor_role == "super_admin":
        return True
    if legacy and actor_role == "admin":
        return target_role in ROLES and target_role != "super_admin"
    privileged = ("super_admin", "admin")
    if target_role in privileged or (current_role in privileged):
        return False
    return actor_role == "admin" and target_role in ROLES


def can_manage(actor_role: str, target_role: str, legacy: bool = False) -> bool:
    """May `actor` suspend / reset / edit an account that has `target_role`?"""
    if actor_role == "super_admin":
        return True
    if actor_role == "admin":
        return legacy or target_role in ("staff", "invigilator", "student")
    return False
