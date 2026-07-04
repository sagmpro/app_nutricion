import bcrypt as _bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request
from sqlalchemy.orm import Session
from app.config import settings
from app.models.user import User


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_session_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.secret_key, algorithm="HS256")


def get_current_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get("nutriplan_session")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id, User.is_active == True).first()
    except (JWTError, ValueError, TypeError):
        return None


def set_session_cookie(response, user_id: int):
    token = create_session_token(user_id)
    response.set_cookie("nutriplan_session", token, max_age=30 * 24 * 3600, httponly=True, samesite="lax")
    return response
