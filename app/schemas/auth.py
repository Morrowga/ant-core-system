from pydantic import BaseModel, EmailStr, Field


class CompanyRegisterRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    timezone: str = "UTC"
    owner_email: EmailStr
    owner_password: str = Field(min_length=8)
    owner_full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(min_length=8)
    full_name: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
