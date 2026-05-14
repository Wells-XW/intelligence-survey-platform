"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.survey_permission import SurveyPermission
from ..models.user import User
from .security import decode_token

# OAuth2 scheme: extracts Bearer token from Authorization header
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

# Role hierarchy — higher value = more permissions
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "owner": 2,
}


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT and return the authenticated User.

    Raises 401 if the token is missing, invalid, expired, or the user
    is deactivated.
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Only access tokens are accepted for API calls
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用访问令牌（非刷新令牌）",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌缺少用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账户已被停用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like ``get_current_user`` but returns None when no token is provided.

    Use for endpoints that behave differently for authenticated vs.
    anonymous users.
    """
    if token is None:
        return None
    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        return None


def _check_role(perm: SurveyPermission, min_role: str) -> None:
    """Raise 403 if the permission's role is below *min_role*."""
    user_level = ROLE_HIERARCHY.get(perm.role, -1)
    required = ROLE_HIERARCHY.get(min_role, 99)
    if user_level < required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足",
        )


async def check_survey_permission(
    survey_id: str,
    user: User,
    min_role: str,
    db: AsyncSession,
) -> SurveyPermission:
    """Verify the user has at least *min_role* on the survey.

    Returns the ``SurveyPermission`` row on success.

    Raises 404 if no permission exists (hides survey existence from
    unauthorized users).
    Raises 403 if the role is insufficient.
    """
    result = await db.execute(
        select(SurveyPermission).where(
            SurveyPermission.survey_id == survey_id,
            SurveyPermission.user_id == user.id,
        )
    )
    perm = result.scalar_one_or_none()

    if perm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="问卷不存在",
        )

    _check_role(perm, min_role)
    return perm
