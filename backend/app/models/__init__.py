"""Import model classes here so Alembic sees all mapped tables."""
from backend.app.models.base import Base
from backend.app.models.user import User

__all__ = ["Base", "User"]
