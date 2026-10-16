"""Validate explicit release configuration before importing application settings."""

import re
from collections.abc import Mapping
from urllib.parse import urlsplit


def validate_environment(environment: Mapping[str, str]) -> None:
    required = (
        "PROJECT_NAME",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "FIRST_SUPERUSER",
        "FRONTEND_HOST",
        "ENVIRONMENT",
    )
    for field in required:
        value = environment.get(field, "")
        if not value or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError(f"configuration: {field} must be explicitly configured")
    for field, minimum in (
        ("SECRET_KEY", 32),
        ("POSTGRES_PASSWORD", 20),
        ("FIRST_SUPERUSER_PASSWORD", 12),
    ):
        value = environment.get(field, "")
        if (
            len(value.strip()) < minimum
            or value != value.strip()
            or "changethis" in value.lower()
        ):
            raise ValueError(
                f"configuration: {field} needs a non-placeholder secret ({minimum}+ characters)"
            )
    if (
        not re.fullmatch(r"[1-9][0-9]{0,4}", environment["POSTGRES_PORT"])
        or int(environment["POSTGRES_PORT"]) > 65535
    ):
        raise ValueError("configuration: POSTGRES_PORT is invalid")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", environment["FIRST_SUPERUSER"]):
        raise ValueError("configuration: FIRST_SUPERUSER must be an email address")
    mode = environment["ENVIRONMENT"]
    if mode not in {"local", "staging", "production"}:
        raise ValueError(
            "configuration: ENVIRONMENT must be local, staging or production"
        )
    origin = environment["FRONTEND_HOST"]
    try:
        url = urlsplit(origin)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path
            or url.query
            or url.fragment
            or url.netloc.endswith(":")
            or (url.port is not None and url.port < 1)
            or any(c.isspace() or c in "\\%*" for c in origin)
            or (mode != "local" and url.scheme != "https")
        ):
            raise ValueError
    except ValueError:
        raise ValueError(
            "configuration: FRONTEND_HOST must be an exact HTTP(S) origin; HTTPS required outside local mode"
        ) from None
