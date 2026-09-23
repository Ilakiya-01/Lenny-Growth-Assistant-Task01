"""Unit tests for configuration helpers."""

from app.config import normalize_database_url


def test_plain_postgresql_url_is_converted_for_sqlalchemy() -> None:
    assert normalize_database_url("postgresql://user:pw@host:5432/db") == (
        "postgresql+psycopg2://user:pw@host:5432/db"
    )


def test_legacy_postgres_scheme_is_converted() -> None:
    assert normalize_database_url("postgres://user:pw@host:5432/db") == (
        "postgresql+psycopg2://user:pw@host:5432/db"
    )


def test_sslmode_is_kept_and_pgbouncer_parameter_is_removed() -> None:
    url = normalize_database_url("postgresql://user:pw@host:6543/db?sslmode=require&pgbouncer=true")
    assert url == "postgresql+psycopg2://user:pw@host:6543/db?sslmode=require"


def test_already_normalised_url_is_unchanged() -> None:
    url = "postgresql+psycopg2://user:pw@host:5432/db"
    assert normalize_database_url(url) == url


def test_empty_url_is_returned_unchanged() -> None:
    assert normalize_database_url("") == ""
