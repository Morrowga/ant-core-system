from pydantic import BaseModel


class IssueCodeResponse(BaseModel):
    code: str
    expires_in: int  # seconds


class ConsumeCodeRequest(BaseModel):
    code: str