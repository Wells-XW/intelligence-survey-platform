"""Authentication API endpoints: register, login, refresh, me."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_audit
from ...core.deps import get_current_user
from ...core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from ...database import get_db
from ...models.consent_record import ConsentRecord
from ...models.refresh_token import RefreshToken
from ...models.user import User
from ...schemas.auth import RefreshRequest, RegisterRequest, TokenResponse
from ...schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account.

    Checks email uniqueness, validates password strength, hashes the
    password, and records PIPL privacy policy consent.
    """
    # Email uniqueness check
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已被注册",
        )

    # Create user
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.flush()

    # Record PIPL privacy policy consent
    consent = ConsentRecord(
        user_id=user.id,
        consent_type="privacy_policy",
        consent_version="v1.0",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(consent)

    # Audit
    await log_audit(
        db,
        action="auth.register",
        user_id=user.id,
        request=request,
    )

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email + password, return token pair.

    Uses OAuth2 form data (``username`` field = email).
    """
    # Look up user
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form.password, user.hashed_password):
        await log_audit(
            db,
            action="auth.login_failed",
            details={"email": form.username},
            request=request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账户已被停用",
        )

    # Issue token pair
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    # Store refresh token hash with JWT expiry
    try:
        payload = decode_token(refresh_token)
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except Exception:
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    rt = RefreshToken(
        token_hash=hash_token(refresh_token),
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(rt)

    await log_audit(
        db,
        action="auth.login",
        user_id=user.id,
        request=request,
    )

    # Calculate expires_in in seconds
    try:
        payload = decode_token(access_token)
        expires_in = payload["exp"] - int(datetime.now(timezone.utc).timestamp())
    except Exception:
        expires_in = 900  # fallback to 15 min

    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=max(0, expires_in),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new token pair.

    Implements one-use rotation: the old refresh token is deleted and
    replaced with a new one, preventing replay attacks.
    """
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌无效或已过期",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请提供刷新令牌",
        )

    user_id = payload.get("sub")
    token_hash = hash_token(body.refresh_token)

    # Verify token exists in DB (not yet used/revoked)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        # Token reuse detected — revoke all refresh tokens for this user
        all_tokens = await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        for t in all_tokens.scalars().all():
            await db.delete(t)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌已被使用（疑似重放攻击，所有令牌已撤销）",
        )

    # Rotate: delete old, create new
    await db.delete(stored)

    access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_token(user_id)

    # Store new refresh token hash
    try:
        new_payload = decode_token(new_refresh_token)
        expires_at = datetime.fromtimestamp(new_payload["exp"], tz=timezone.utc)
    except Exception:
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    db.add(
        RefreshToken(
            token_hash=hash_token(new_refresh_token),
            user_id=user_id,
            expires_at=expires_at,
        )
    )

    await log_audit(
        db,
        action="auth.refresh",
        user_id=user_id,
        request=request,
    )

    try:
        acc_payload = decode_token(access_token)
        expires_in = acc_payload["exp"] - int(datetime.now(timezone.utc).timestamp())
    except Exception:
        expires_in = 900

    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=max(0, expires_in),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return user
