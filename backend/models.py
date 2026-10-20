"""Modelo de dados (seção 7 do plano). Nenhuma tabela tem campo de chave privada."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base, agora


class Server(Base):
    """Nó lógico de retransmissão (RF13). O nome é único: é ele que aparece nos saltos."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    host: Mapped[str] = mapped_column(String(120), default="127.0.0.1")
    porta: Mapped[int] = mapped_column(Integer, default=8000)
    regiao: Mapped[str] = mapped_column(String(60), default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    capacidade: Mapped[int] = mapped_column(Integer, default=100)


class ServerLink(Base):
    """Ligação entre dois nós, sem direção (guardada com a_id < b_id): por onde um envelope pode passar."""

    __tablename__ = "server_links"

    a_id: Mapped[int] = mapped_column(ForeignKey("servers.id"), primary_key=True)
    b_id: Mapped[int] = mapped_column(ForeignKey("servers.id"), primary_key=True)


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
    servidor: Mapped[Server | None] = relationship()


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


class KeyChallenge(Base):
    """Nonce de uso único para a troca de chave (prova de posse da nova privada)."""

    __tablename__ = "key_challenges"

    nonce: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime)
    usado: Mapped[bool] = mapped_column(Boolean, default=False)


class KeyAccess(Base):
    """Quem buscou a chave de quem: define quem é avisado na troca ou exclusão."""

    __tablename__ = "key_access"
    __table_args__ = (UniqueConstraint("client_id", "owner_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    key_id: Mapped[str] = mapped_column(String(20))
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(6))  # 1:1 / grupo
    modo: Mapped[str] = mapped_column(String(10))
    e2e_ativo: Mapped[bool] = mapped_column(Boolean, default=True)  # só para a demonstração RF16
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    membros: Mapped[list[Client]] = relationship(secondary="participants", order_by="Client.username")


class Participant(Base):
    __tablename__ = "participants"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), primary_key=True)


class Message(Base):
    """Cabeçalho da mensagem, sem conteúdo: o conteúdo só existe cifrado, nos envelopes."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # message_id gerado pelo cliente
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    sent_at: Mapped[str] = mapped_column(String(40))  # declarado pelo remetente (vai assinado)
    recebida_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    hops: Mapped[str] = mapped_column(Text, default="[]")


class EnvelopeRegistro(Base):
    """Um envelope por destinatário. status pendente = fila offline."""

    __tablename__ = "envelopes"
    __table_args__ = (UniqueConstraint("message_id", "recipient_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    to_key_id: Mapped[str] = mapped_column(String(20))
    conteudo: Mapped[str] = mapped_column(Text)  # o envelope em JSON, exatamente como o remetente assinou
    status: Mapped[str] = mapped_column(String(10), default="pendente")  # pendente / entregue
    entregue_em: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    hops: Mapped[str] = mapped_column(Text, default="[]")  # nomes dos nós do último caminho calculado


class KeyEvent(Base):
    """Auditoria: criada, substituida, revogada."""

    __tablename__ = "key_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))
    key_id: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)


class TraceRegistro(Base):
    """TraceEvent do servidor: só eventos de trânsito, com o que ele enxerga (nunca texto claro)."""

    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    etapa: Mapped[str] = mapped_column(String(20))  # recebido / salto / entregue / fila / confirmado
    ator: Mapped[str] = mapped_column(String(80))  # nome do nó (ou "relay" sem nós cadastrados)
    entrada: Mapped[str] = mapped_column(Text, default="null")  # JSON
    saida: Mapped[str] = mapped_column(Text, default="null")  # JSON
    duracao_ms: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)
