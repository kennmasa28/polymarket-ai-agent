"""Generate a password hash for the web app login.

    python -m webapp.passwords 'your-password'

Set the printed value as ``POLYAGENT_PASSWORD_HASH``.
"""

from __future__ import annotations

import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> None:
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("パスワード: ")
    if not password:
        raise SystemExit("パスワードを指定してください。")
    print(generate_password_hash(password, method="scrypt"))


if __name__ == "__main__":
    main()
