"""Reset a local NextPanel password from an interactive operator terminal."""

import argparse
import asyncio
import warnings
from getpass import GetPassWarning, getpass

from pydantic import ValidationError
from sqlalchemy import delete, select

from .config import config
from .db import session_scope
from .models import User, UserSession
from .schemas import CredentialsIn
from .security import hash_password


async def _reset_password(credentials: CredentialsIn) -> bool:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.username == credentials.username))
        if user is None or user.sso_only:
            return False
        user.password_hash = hash_password(credentials.password)
        await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
        await session.commit()
        return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="exact username of the existing local account")
    args = parser.parse_args(argv)
    if not config.db_path.is_file():
        parser.exit(1, "NextPanel database not found. Check NEXTPANEL_DATA_DIR.\n")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("New NextPanel password: ")
            confirmation = getpass("Confirm password: ")
    except (EOFError, GetPassWarning):
        parser.exit(1, "Run the password reset in an interactive terminal.\n")

    if password != confirmation:
        parser.exit(1, "The passwords do not match.\n")
    try:
        credentials = CredentialsIn(username=args.username, password=password)
    except ValidationError:
        parser.exit(1, "Use an existing username and a password of 8 to 128 characters.\n")

    if not asyncio.run(_reset_password(credentials)):
        parser.exit(1, "No local account matches that exact username.\n")
    print("Password reset. Existing NextPanel sessions for this account were revoked.")


if __name__ == "__main__":
    main()
