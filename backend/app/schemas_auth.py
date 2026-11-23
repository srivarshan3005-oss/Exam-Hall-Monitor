from pydantic import BaseModel, Field, field_validator
from .schemas import RegisterNumber


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=128)
    register_number: RegisterNumber
    email: str = Field(min_length=5, max_length=150)

    @field_validator("username", "email")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower()


class ActivateInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ForgotInput(BaseModel):
    identifier: str = Field(min_length=3, max_length=150)


class ResetInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=128)


class AdminResetInput(BaseModel):
    reason: str = Field(min_length=5, max_length=200)


class StatusInput(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
