import hmac

from fastapi import Request

from app.config import get_settings

COOKIE_NAME = "paper_archive_auth"


def auth_token() -> str:
    settings = get_settings()
    return hmac.new(
        settings.app_secret_key.encode(),
        settings.shared_password.encode(),
        "sha256",
    ).hexdigest()


def is_authenticated(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), auth_token())

