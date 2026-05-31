from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import User
from app.core.auth import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    username = decode_access_token(token)
    if not username:
        raise _credentials_exc
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise _credentials_exc
    return user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    """Gate write/control endpoints: only `owner` may pass; `viewer` is read-only."""
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )
    return current_user
