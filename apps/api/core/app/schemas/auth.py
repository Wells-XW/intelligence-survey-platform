"""Authentication schemas: register, login, token refresh."""

from pydantic import BaseModel, EmailStr, model_validator

from ..core.security import validate_password


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str
    display_name: str

    @model_validator(mode="after")
    def check_password(self) -> "RegisterRequest":
        is_valid, error = validate_password(self.password)
        if not is_valid:
            raise ValueError(error)
        return self


class LoginRequest(BaseModel):
    """Request body for JSON-based login (alternative to form data)."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Bearer token pair returned after login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshRequest(BaseModel):
    """Request body for refreshing an expired access token."""

    refresh_token: str
