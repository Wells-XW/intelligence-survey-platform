"""Authentication schemas: register, login, token refresh."""

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "researcher@example.edu",
                    "password": "L1@n9-Xu3Sh3n!",
                    "display_name": "李雪松",
                }
            ]
        }
    )


class LoginRequest(BaseModel):
    """Request body for JSON-based login (alternative to form data)."""

    email: EmailStr
    password: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "researcher@example.edu",
                    "password": "L1@n9-Xu3Sh3n!",
                }
            ]
        }
    )


class TokenResponse(BaseModel):
    """Bearer token pair returned after login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": (
                        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                        "eyJzdWIiOiJhMWIyYzNkNCIsImV4cCI6MTczMDAwMDAwMH0."
                        "Q9YfQ-eXAMPLEsignaturevalueonly"
                    ),
                    "refresh_token": (
                        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                        "eyJzdWIiOiJhMWIyYzNkNCIsInR5cGUiOiJyZWZyZXNoIn0."
                        "Q9YfQ-eXAMPLErefreshsignature"
                    ),
                    "token_type": "bearer",
                    "expires_in": 900,
                }
            ]
        }
    )


class RefreshRequest(BaseModel):
    """Request body for refreshing an expired access token."""

    refresh_token: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "refresh_token": (
                        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                        "eyJzdWIiOiJhMWIyYzNkNCIsInR5cGUiOiJyZWZyZXNoIn0."
                        "Q9YfQ-eXAMPLErefreshsignature"
                    )
                }
            ]
        }
    )
