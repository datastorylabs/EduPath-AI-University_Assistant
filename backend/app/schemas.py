"""Validated authentication request and response schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime

    @classmethod
    def from_user(cls, user) -> "UserResponse":
        return cls(id=user.id, email=user.email, created_at=user.created_at)


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    expires_at: datetime
