"""Proactively DM a user by email (onboarding / Jarvis outreach).

  OPS_SA_KEY=/tmp/sa-key.json python scripts/dm_user.py <email> "<message>" [--admin]

--admin also registers their DM space so the nightly summary reaches them.
Requires the Directory API scope authorized for the SA's DWD client.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import directory


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    email, text = sys.argv[1], sys.argv[2]
    register = "--admin" in sys.argv[3:]
    print(directory.dm_email(email, text, register_admin=register))


if __name__ == "__main__":
    main()
