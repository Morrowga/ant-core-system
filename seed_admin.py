"""One-off seed script -- creates (or updates) the first platform admin
account. Safe to run more than once: if the email already exists, it just
resets the password instead of failing on the unique constraint.

Run with:
    docker-compose exec worker python seed_admin.py
"""
from app.core.admin_auth import hash_admin_password
from app.models.company import PlatformAdmin
from app.workers.celery_app import SyncSessionLocal

EMAIL = "ant@gmail.com"
PASSWORD = "Password"
FULL_NAME = "Ant Admin"


def main() -> None:
    with SyncSessionLocal() as db:
        existing = db.query(PlatformAdmin).filter(PlatformAdmin.email == EMAIL).first()
        if existing:
            existing.password_hash = hash_admin_password(PASSWORD)
            existing.active = True
            db.commit()
            print(f"Updated existing admin '{EMAIL}' (id={existing.id}) with new password.")
            return

        admin = PlatformAdmin(
            email=EMAIL,
            password_hash=hash_admin_password(PASSWORD),
            full_name=FULL_NAME,
        )
        db.add(admin)
        db.commit()
        print(f"Created admin '{EMAIL}' (id={admin.id}).")


if __name__ == "__main__":
    main()