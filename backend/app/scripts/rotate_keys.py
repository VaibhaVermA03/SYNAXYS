"""Re-encrypt stored GitHub tokens with the FIRST key in ENCRYPTION_KEY.

Rotation procedure (see SECURITY.md):
  1. Generate a new key and PREPEND it:  ENCRYPTION_KEY=<new>,<old>
  2. Restart API and worker (both can still decrypt old tokens).
  3. Run:  python -m app.scripts.rotate_keys          (add --dry-run to only count)
  4. When it reports 0 tokens still on an old key, remove <old> from ENCRYPTION_KEY and restart.
"""
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import OAuthIdentity


def main(dry_run: bool = False) -> int:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet
    keys = [k.strip() for k in get_settings().encryption_key.split(",") if k.strip()]
    if not keys:
        print("ENCRYPTION_KEY is not configured.")
        return 1
    primary, multi = Fernet(keys[0].encode()), MultiFernet([Fernet(k.encode()) for k in keys])
    rotated = current = failed = 0
    with SessionLocal() as db:
        for ident in db.scalars(select(OAuthIdentity).where(OAuthIdentity.access_token_enc.is_not(None))).all():
            token = ident.access_token_enc.encode()
            try:
                primary.decrypt(token)          # already on the primary key
                current += 1
                continue
            except InvalidToken:
                pass
            try:
                new = multi.rotate(token).decode()
            except InvalidToken:
                failed += 1                      # undecryptable with every configured key: the user must sign in again
                continue
            rotated += 1
            if not dry_run:
                ident.access_token_enc = new
        if not dry_run:
            db.commit()
    print(f"{'would rotate' if dry_run else 'rotated'}: {rotated}; already current: {current}; undecryptable (re-login needed): {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
