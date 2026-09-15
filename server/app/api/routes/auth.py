from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep, issue_refresh_token, write_audit
from app.models import RefreshToken, User, utcnow
from app.schemas.api import LoginRequest, RefreshRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_token, token_matches, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbDep, request: Request):
    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        await write_audit(db, "auth.login_failed", details={"username": body.username}, request=request)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    raw, hashed, expires = issue_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=expires))
    user.last_login_at = utcnow()
    await write_audit(db, "auth.login", user=user, request=request)
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role, user.username),
        refresh_token=raw,
        role=user.role,
        username=user.username,
        user_id=user.id,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbDep):
    hashed = hash_token(body.refresh_token)
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hashed))).scalar_one_or_none()
    if not row or row.revoked or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    user = await db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled")
    row.revoked = True
    raw, new_hash, expires = issue_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=new_hash, expires_at=expires))
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role, user.username),
        refresh_token=raw,
        role=user.role,
        username=user.username,
        user_id=user.id,
    )


@router.post("/logout")
async def logout(body: RefreshRequest, db: DbDep, user: CurrentUser, request: Request):
    hashed = hash_token(body.refresh_token)
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hashed))).scalar_one_or_none()
    if row:
        row.revoked = True
    await write_audit(db, "auth.logout", user=user, request=request)
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
