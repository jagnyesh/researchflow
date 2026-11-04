"""Create a user directly in the app database.

The way to get a first admin: POST /users itself requires an admin, and the
hardcoded MOCK_USERS login fallback is gone (#280). The password is read from
a prompt, never argv, so it stays out of shell history.

    python scripts/create_user.py admin@example.org "First Admin" --role admin
"""

import argparse
import asyncio
import getpass
import sys
import uuid
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import get_db_session, init_db  # noqa: E402
from app.database.models import User as UserModel  # noqa: E402
from app.schemas.users import Role  # noqa: E402
from app.security.auth import get_password_hash  # noqa: E402


async def create_user(email: str, password: str, role: str, full_name: str) -> str:
    if role not in get_args(Role):
        raise ValueError(f"role must be one of {get_args(Role)}")

    await init_db()
    async with get_db_session() as session:
        existing = await session.execute(select(UserModel).filter(UserModel.email == email))
        if existing.scalar_one_or_none():
            raise ValueError(f"{email} already exists")

        user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
        session.add(
            UserModel(
                id=user_id,
                email=email,
                hashed_password=get_password_hash(password),
                full_name=full_name,
                role=role,
                is_active=True,
            )
        )
    return user_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("full_name")
    parser.add_argument("--role", default="researcher", choices=get_args(Role))
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if not password or password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords are empty or don't match.")

    user_id = asyncio.run(create_user(args.email, password, args.role, args.full_name))
    print(f"Created {args.role} {user_id}")


if __name__ == "__main__":
    main()
