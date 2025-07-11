from pydantic import BaseModel, EmailStr


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_info: dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    username: str  # Can be phone_number or email
    password: str


class UserInfoResponse(BaseModel):
    employee_code: str
    name: str
    email: EmailStr
    phone_number: str
    role: str
    branch_id: int = None
    is_active: bool
