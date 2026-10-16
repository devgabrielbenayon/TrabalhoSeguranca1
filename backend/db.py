"""Conexão com o banco (SQLite por padrão)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

URL_PADRAO = os.environ.get("CRIPTOCHAT_DB", "sqlite:///data/criptochat.db")


class Base(DeclarativeBase):
    pass


def agora() -> datetime:
    """UTC sem fuso: o SQLite não guarda fuso, então todo o back-end usa UTC ingênuo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def criar_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url)
    opcoes: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        opcoes["poolclass"] = StaticPool  # mesmo banco em memória para todas as conexões (testes)
    else:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **opcoes)


def criar_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as sessao:
        yield sessao
