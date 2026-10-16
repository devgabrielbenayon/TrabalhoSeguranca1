"""Modelo de dados (seção 7 do plano). Nenhuma tabela tem campo de chave privada."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base, agora


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    host: Mapped[str] = mapped_column(String(120), default="127.0.0.1")
    porta: Mapped[int] = mapped_column(Integer, default=8000)
    regiao: Mapped[str] = mapped_column(String(60), default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    capacidade: Mapped[int] = mapped_column(Integer, default=100)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(80))
    senha_hash: Mapped[str] = mapped_column(String(200))
    avatar: Mapped[str | None] = mapped_column(String(200), default=None)
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id"), default=None)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    chaves: Mapped[list[PublicKey]] = relationship(back_populates="dono")


class PublicKey(Base):
    __tablename__ = "public_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    modo: Mapped[str] = mapped_column(String(10))
    public_key: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="ativa")  # ativa / substituida / revogada
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    substituida_em: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    dono: Mapped[Client] = relationship(back_populates="chaves")


class Sessao(Base):
    """Token de login. Guarda só o SHA-256 do token: vazar o banco não vaza sessões."""

    __tablename__ = "sessoes"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime)


class KeyAccess(Base):
    """Quem buscou a chave de quem: define quem é avisado na troca ou exclusão."""

    __tablename__ = "key_access"
    __table_args__ = (UniqueConstraint("client_id", "owner_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    key_id: Mapped[str] = mapped_column(String(20))
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)


class KeyEvent(Base):
    """Auditoria: criada, substituida, revogada."""

    __tablename__ = "key_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))
    key_id: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)
