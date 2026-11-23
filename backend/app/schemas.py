import re
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict, AfterValidator, field_validator, model_validator
from .regno import normalize_register_number


def _reg(value: str) -> str:
    try:
        return normalize_register_number(value)
    except ValueError as exc:
        raise ValueError(str(exc))


RegisterNumber = Annotated[str, AfterValidator(_reg)]
_WS = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{2,}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SUBJECT = re.compile(r"^[A-Z0-9][A-Z0-9 _/\-]{1,29}$")
_SEAT = re.compile(r"^[A-Z0-9][A-Z0-9 \-/]{0,29}$")
Role = Literal["super_admin", "admin", "staff", "invigilator", "student"]


def _tidy(value: str) -> str:
    return _WS.sub(" ", value).strip()


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    # No minimum here: the password policy applies when a password is SET, not when it is checked.
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class StudentCreate(BaseModel):
    register_number: RegisterNumber
    full_name: str = Field(min_length=2, max_length=150)
    department: str = Field(min_length=2, max_length=100)
    year: int = Field(ge=1, le=6)
    email: str | None = Field(default=None, max_length=150)
    course: str | None = Field(default=None, max_length=100)

    _t = field_validator("full_name", "department")(_tidy)

    @field_validator("course")
    @classmethod
    def _course(cls, v):
        return (_tidy(v) or None) if v else None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v in (None, ""):
            return None
        if not _EMAIL.match(v):
            raise ValueError("Invalid e-mail address")
        return v.lower()


class StudentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    department: str | None = Field(default=None, min_length=2, max_length=100)
    year: int | None = Field(default=None, ge=1, le=6)
    email: str | None = Field(default=None, max_length=150)
    active: bool | None = None
    course: str | None = Field(default=None, max_length=100)

    @field_validator("course")
    @classmethod
    def _course(cls, v):
        return (_tidy(v) or None) if v else None

    @field_validator("full_name", "department")
    @classmethod
    def _tidy_opt(cls, v):
        return _tidy(v) if v is not None else v

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v in (None, ""):
            return None
        if not _EMAIL.match(v):
            raise ValueError("Invalid e-mail address")
        return v.lower()


def _check_date(v: str) -> str:
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("exam_date must be a real date in YYYY-MM-DD format")
    return v


def _check_subject(v: str) -> str:
    v = _tidy(v).upper()
    if not _SUBJECT.match(v):
        raise ValueError("subject_code may contain letters, digits, space, '-', '_' or '/'")
    return v


class ExamCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    subject_code: str | None = Field(default=None, min_length=2, max_length=30)
    exam_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    venue: str = Field(default="To be announced", max_length=150)
    status: Literal["draft", "published", "completed"] = "draft"
    subject_id: int | None = Field(default=None, ge=1)
    term_id: int | None = Field(default=None, ge=1)

    _title = field_validator("title", "venue")(_tidy)
    _date = field_validator("exam_date")(_check_date)

    @field_validator("subject_code")
    @classmethod
    def _subj(cls, v):
        return _check_subject(v) if v is not None else v

    @field_validator("start_time", "end_time")
    @classmethod
    def _time(cls, v):
        if not _TIME.match(v):
            raise ValueError("Time must be HH:MM (24-hour)")
        return v

    @model_validator(mode="after")
    def _order(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        if not self.subject_code and not self.subject_id:
            raise ValueError("Provide subject_id (catalogue) or subject_code")
        return self


class ExamUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    subject_code: str | None = Field(default=None, min_length=2, max_length=30)
    exam_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    venue: str | None = Field(default=None, max_length=150)
    status: Literal["draft", "published", "completed"] | None = None
    subject_id: int | None = Field(default=None, ge=1)
    term_id: int | None = Field(default=None, ge=1)

    @field_validator("title", "venue")
    @classmethod
    def _t(cls, v):
        return _tidy(v) if v is not None else v

    @field_validator("subject_code")
    @classmethod
    def _s(cls, v):
        return _check_subject(v) if v is not None else v

    @field_validator("exam_date")
    @classmethod
    def _d(cls, v):
        return _check_date(v) if v is not None else v

    @field_validator("start_time", "end_time")
    @classmethod
    def _tm(cls, v):
        if v is not None and not _TIME.match(v):
            raise ValueError("Time must be HH:MM (24-hour)")
        return v


class AllotmentCreate(BaseModel):
    register_number: RegisterNumber
    exam_id: int = Field(ge=1)
    hall: str = Field(min_length=1, max_length=100)
    seat: str = Field(min_length=1, max_length=30)

    @field_validator("hall")
    @classmethod
    def _hall(cls, v):
        return _tidy(v).upper()

    @field_validator("seat")
    @classmethod
    def _seat_v(cls, v):
        v = _tidy(v).upper()
        if not _SEAT.match(v):
            raise ValueError("seat may contain letters, digits, space, '-' or '/'")
        return v


class AutoAllocationInput(BaseModel):
    exam_id: int = Field(ge=1)
    register_numbers: list[RegisterNumber] | None = Field(default=None, max_length=10000)
    hall_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)
    # Phase 2 rules (defaults reproduce the Phase 1 behaviour exactly)
    strategy: Literal["balanced", "sequential"] = "balanced"
    seat_gap: int = Field(default=0, ge=0, le=5)
    department_separation: Literal["off", "preferred", "strict"] = "off"

    @field_validator("hall_ids")
    @classmethod
    def unique_halls(cls, value):
        if value is not None and (any(v < 1 for v in value) or len(set(value)) != len(value)):
            raise ValueError("hall_ids must contain unique positive IDs")
        return value

    @field_validator("register_numbers")
    @classmethod
    def unique_registers(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("register_numbers must be unique")
        return value


class ResultCreate(BaseModel):
    register_number: RegisterNumber
    exam_id: int = Field(ge=1)
    marks: float = Field(ge=0)
    max_marks: float = Field(gt=0)
    grade: str = Field(default="—", min_length=1, max_length=5)
    published: bool = False

    @model_validator(mode="after")
    def _bounds(self):
        if self.marks > self.max_marks:
            raise ValueError("Marks cannot exceed maximum marks")
        return self


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=128)
    role: Role
    student_register_number: RegisterNumber | None = None
    email: str | None = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str | None = Field(default=None, max_length=100)
    require_password_change: bool = False

    @field_validator("username")
    @classmethod
    def _lower(cls, v):
        return v.lower()


class UserUpdate(BaseModel):
    role: Role | None = None
    active: bool | None = None
    unlock: bool | None = None
    new_password: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=150, pattern=r"^([^@\s]+@[^@\s]+\.[^@\s]+)?$")
    department: str | None = Field(default=None, max_length=100)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------------- Phase 2
def _opt_tidy(v):
    return (_tidy(v) or None) if isinstance(v, str) else v


class SubjectInput(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    semester: int | None = Field(default=None, ge=1, le=12)
    credits: float | None = Field(default=None, ge=0, le=50)
    active: bool = True

    _code = field_validator("code")(_check_subject)
    _name = field_validator("name")(_tidy)
    _dept = field_validator("department")(_opt_tidy)


class SubjectUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=30)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    semester: int | None = Field(default=None, ge=1, le=12)
    credits: float | None = Field(default=None, ge=0, le=50)
    active: bool | None = None

    @field_validator("code")
    @classmethod
    def _c(cls, v):
        return _check_subject(v) if v is not None else v

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _tidy(v) if v is not None else v

    _dept = field_validator("department")(_opt_tidy)


class AcademicYearInput(BaseModel):
    label: str = Field(pattern=r"^\d{4}(-\d{2,4})?$", max_length=20)
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def _ord(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class ExamTermInput(BaseModel):
    academic_year_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=150)
    semester_no: int | None = Field(default=None, ge=1, le=12)
    start_date: date
    end_date: date
    active: bool = True

    _name = field_validator("name")(_tidy)

    @model_validator(mode="after")
    def _ord(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class EligibilityRuleInput(BaseModel):
    department: str | None = Field(default=None, max_length=100)
    course: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1, le=6)

    _d = field_validator("department", "course")(_opt_tidy)

    @model_validator(mode="after")
    def _not_empty(self):
        if self.department is None and self.course is None and self.year is None:
            raise ValueError("A rule needs at least a department, course or year")
        return self


class EligibilityInput(BaseModel):
    """Replaces the exam's whole audience definition atomically."""
    rules: list[EligibilityRuleInput] = Field(default_factory=list, max_length=200)
    include: list[RegisterNumber] = Field(default_factory=list, max_length=5000)
    exclude: list[RegisterNumber] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _disjoint(self):
        if set(self.include) & set(self.exclude):
            raise ValueError("A student cannot be both included and excluded")
        return self


class PlanInput(AutoAllocationInput):
    pass


class PlanCommitInput(BaseModel):
    allow_partial: bool = False


class AllotmentMove(BaseModel):
    hall: str = Field(min_length=1, max_length=100)
    seat: str = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("hall")
    @classmethod
    def _h(cls, v):
        return _tidy(v).upper()

    @field_validator("seat")
    @classmethod
    def _s(cls, v):
        v = _tidy(v).upper()
        if not _SEAT.match(v):
            raise ValueError("seat may contain letters, digits, space, '-' or '/'")
        return v

    @field_validator("reason")
    @classmethod
    def _r(cls, v):
        return _tidy(v)
