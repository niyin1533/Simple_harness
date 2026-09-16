"""@input CLI arguments and database. @output Initialization and administrator accounts.
@position Operations entry. @doc-sync Update INDEX.md on changes.
"""

import argparse
import asyncio
import getpass
import os
import secrets
from cryptography.fernet import Fernet
from sqlalchemy import select
from .config import settings
from .db import engine, DB, User, Resource
from .security import hasher


async def initialize(username, password):
    if len(password) < 10:
        raise ValueError("管理员密码至少 10 字符")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "master.key"
    if not path.exists():
        with path.open("xb") as f:
            f.write(Fernet.generate_key())
        if os.name != "nt":
            path.chmod(0o600)
    async with DB.begin() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if not user:
            db.add(User(username=username, password=hasher.hash(password), admin=True))
        else:
            print("Existing account preserved; password was not changed.")
        for runtime, name in [
            ("yolo", "YOLO · Ultralytics"),
            ("yolov5", "YOLOv5 · 本地仓库"),
            ("minimax", "MiniMax · 语音与图像"),
        ]:
            id = "template." + runtime
            if not await db.get(Resource, id):
                db.add(
                    Resource(
                        id=id,
                        kind="template",
                        name=name,
                        config={"runtime": runtime, "python": "", "script": ""},
                    )
                )
    await engine.dispose()
    print("Initialized independent Agent Harness database and templates.")
    return user is None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init"])
    parser.add_argument("--username", default="admin")
    parser.add_argument("--generate-password", action="store_true")
    args = parser.parse_args()
    password = (
        secrets.token_urlsafe(18)
        if args.generate_password
        else os.environ.get("AGENT_INITIAL_PASSWORD")
        or getpass.getpass("Administrator password: ")
    )
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    created = asyncio.run(initialize(args.username, password))
    if args.generate_password and created:
        path = settings.data_dir / "initial-admin.txt"
        with path.open("x", encoding="utf-8") as file:
            file.write("username=" + args.username + "\npassword=" + password + "\n")
        if os.name != "nt":
            path.chmod(0o600)
        print(
            "Initial credentials saved to "
            + str(path)
            + "; remove after securely recording them."
        )


if __name__ == "__main__":
    main()
