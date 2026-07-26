from pydantic import BaseModel, EmailStr, Field


class CompanyRegisterRequest(BaseModel):
    """Registers an Organization (the real account/billing entity) AND its
    first Company (a "project" under it) in one call.

    organization_name and company_name are DELIBERATELY separate fields --
    an Organization is the container ("Acme Holdings"), a Company is one
    thing it operates ("Acme Coffee Shop #1"). These are often the same
    string for a small business registering for the first time, which is
    why company_name defaults to organization_name when omitted -- but they
    are never the same FIELD, and register_company() must never collapse
    them back into one value. Getting this wrong here is the one mistake
    that's expensive to undo later, since every Company/CompanyModule/
    billing relationship in the system hangs off which Organization a
    Company actually belongs to.
    """
    organization_name: str = Field(min_length=2, max_length=255)
    company_name: str | None = Field(default=None, min_length=2, max_length=255)
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