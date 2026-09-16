"""@input Sessions and cryptography. @output Login dependencies and protected secrets.
@position Authentication and auditing. @doc-sync Update header and INDEX.md on changes.
"""

import hashlib
import re
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import Request, HTTPException, Depends
from .db import DB, Login, User, now
from .config import settings

hasher = PasswordHasher()


def cipher():
    path = settings.data_dir / "master.key"
    if not path.exists():
        raise RuntimeError("请先运行 python -m app.cli init 初始化主密钥")
    return Fernet(path.read_bytes())


def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else None


def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value else ""


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sanitize(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if re.search(r"key|token|secret|password|authorization|cookie", k, re.I)
            else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(Bearer\s+)[\w.\-]+", r"\1[REDACTED]", value)
    return value


async def current_user(request: Request):
    token = request.cookies.get("agent_session", "")
    async with DB() as db:
        login = await db.get(Login, digest(token))
        if not login or login.expires < now():
            raise HTTPException(401, "请登录")
        user = await db.get(User, login.user_id)
        if not user or not user.active:
            raise HTTPException(401, "账户已停用")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-CSRF-Token") != login.csrf:
                raise HTTPException(403, "CSRF 校验失败")
        return user


async def administrator(user=Depends(current_user)):
    if not user.admin:
        raise HTTPException(403, "此操作需要管理员权限")
    return user
