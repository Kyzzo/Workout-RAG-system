import base64
import os

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from . import models
from .database import get_db

load_dotenv()

CLERK_PUBLISHABLE_KEY = os.environ["CLERK_PUBLISHABLE_KEY"]
CLERK_ALLOWED_ORIGINS = os.environ["CLERK_ALLOWED_ORIGINS"].split(",")

if CLERK_PUBLISHABLE_KEY.startswith("pk_test_"):
    _encoded_domain = CLERK_PUBLISHABLE_KEY[len("pk_test_"):]
elif CLERK_PUBLISHABLE_KEY.startswith("pk_live_"):
    _encoded_domain = CLERK_PUBLISHABLE_KEY[len("pk_live_"):]
else:
    raise ValueError("Unrecognized Clerk publishable key format")

CLERK_FRONTEND_API = base64.b64decode(_encoded_domain).decode("utf-8").rstrip("$")
CLERK_JWKS_URL = f"https://{CLERK_FRONTEND_API}/.well-known/jwks.json"

_jwk_client = PyJWKClient(CLERK_JWKS_URL)

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    token = credentials.credentials

    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=["RS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("azp") not in CLERK_ALLOWED_ORIGINS:
        raise HTTPException(status_code=401, detail="Token issued for an unrecognized origin")

    clerk_user_id = payload["sub"]

    user = db.query(models.User).filter(models.User.clerk_user_id == clerk_user_id).first()
    if user is None:
        user = models.User(clerk_user_id=clerk_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user
