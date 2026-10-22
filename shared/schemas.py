"""Schemas Pydantic compartilhados entre back-end e front-end."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Modo = Literal["didatico", "real"]
StatusChave = Literal["ativa", "substituida", "revogada"]
USERNAME_REGEX = r"^[a-z0-9_]{3,20}$"


# ---------------------------------------------------------------- cadastro e login (Passo 0)


class ChavePublicaIn(BaseModel):
    modo: Modo
    public_key: str = Field(description="JSON {e, n} no modo didático, PEM no modo real")
    prova: str = Field(description="base64 da assinatura de mensagem_prova('registro', …) com a privada")


class RegistroIn(BaseModel):
    username: str = Field(pattern=USERNAME_REGEX)
    nome: str = Field(min_length=1, max_length=80)
    senha: str = Field(min_length=6, max_length=128)
    chaves: list[ChavePublicaIn] = Field(min_length=1, max_length=2)

    @field_validator("chaves")
    @classmethod
    def um_por_modo(cls, chaves: list[ChavePublicaIn]) -> list[ChavePublicaIn]:
        if len({c.modo for c in chaves}) != len(chaves):
            raise ValueError("envie no máximo uma chave por modo")
        return chaves


class LoginIn(BaseModel):
    username: str
    senha: str


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nome: str
    avatar: str | None = None
    is_admin: bool = False


class TokenOut(BaseModel):
    token: str
    expira_em: datetime
    usuario: UsuarioOut


# ---------------------------------------------------------------- diretório de chaves


class ChavePublicaOut(BaseModel):
    username: str
    modo: Modo
    key_id: str
    public_key: str
    fingerprint: str
    status: StatusChave
    criada_em: datetime


class RegistroOut(BaseModel):
    usuario: UsuarioOut
    chaves: list[ChavePublicaOut]


class DiretorioOut(BaseModel):
    chaves: dict[str, ChavePublicaOut] = Field(description="username → chave ativa no modo pedido")
    sem_chave: list[str] = Field(description="usuários inexistentes ou sem chave ativa nesse modo")


# ---------------------------------------------------------------- troca e exclusão (fluxos 5.4 e 5.5)


class DesafioOut(BaseModel):
    nonce: str
    expira_em: datetime


class TrocaChaveIn(BaseModel):
    modo: Modo
    public_key: str
    nonce: str
    prova: str = Field(description="base64 da assinatura de mensagem_prova('troca', username, key_id, nonce) com a NOVA privada")


class ExclusaoChaveIn(BaseModel):
    modo: Modo
    senha: str = Field(description="reautenticação: um token roubado não basta para excluir a chave")


# ---------------------------------------------------------------- conversas


class ConversaIn(BaseModel):
    participantes: list[str] = Field(min_length=1, max_length=20, description="os outros participantes (sem você)")
    modo: Modo = "real"


class ConversaOut(BaseModel):
    id: int
    tipo: Literal["1:1", "grupo"]
    modo: Modo
    participantes: list[str]
    e2e_ativo: bool
    criada_em: datetime


# ---------------------------------------------------------------- mensagens

MESSAGE_ID_REGEX = r"^[0-9a-f]{32}$"
MAX_BLOCOS = 16384  # 2.000 caracteres (até 8.000 bytes em UTF-8) + cabeçalho, com blocos de 1 byte (n de 16 bits)


class Envelope(BaseModel):
    """Um envelope por destinatário (seção 8.3 do plano). Blocos e assinatura em base64."""

    model_config = ConfigDict(populate_by_name=True)

    message_id: str
    conversation_id: int
    from_: str = Field(alias="from")
    from_key_id: str
    to: str
    to_key_id: str
    mode: Modo
    sent_at: str
    blocks: list[Annotated[str, Field(max_length=1024)]] = Field(min_length=1, max_length=MAX_BLOCOS)
    signature: str = Field(default="", max_length=1024)

    def dados_assinados(self) -> bytes:
        """JSON canônico de todos os campos exceto a assinatura."""
        campos = self.model_dump(by_alias=True, exclude={"signature"})
        return json.dumps(campos, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def para_json(self) -> dict:
        return self.model_dump(by_alias=True)


# ---------------------------------------------------------------- protocolo WebSocket (seção 8.2)


class EnvioWS(BaseModel):
    """Cliente → servidor: uma mensagem = um envelope por participante (inclusive a cópia do remetente)."""

    type: Literal["send"]
    message_id: str = Field(pattern=MESSAGE_ID_REGEX)
    conversation_id: int
    envelopes: list[Envelope] = Field(min_length=1, max_length=21)


class AckWS(BaseModel):
    """Cliente → servidor: confirma que recebeu (e processou) o envelope."""

    type: Literal["ack"]
    message_id: str = Field(pattern=MESSAGE_ID_REGEX)


# ---------------------------------------------------------------- CRUD de clientes (RF12)


class ClienteOut(BaseModel):
    id: int
    username: str
    nome: str
    avatar: str | None = None
    is_admin: bool
    ativo: bool
    criado_em: datetime
    server_id: int | None
    servidor: str | None = Field(description="nome do nó onde o cliente está")
    modos_ativos: list[Modo] = Field(description="modos em que o cliente tem chave pública ativa")
    online: bool


class ClienteEdicaoIn(BaseModel):
    """Campos omitidos não mudam. O próprio usuário edita nome e avatar; nó, papel e reativação são do administrador."""

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    avatar: str | None = Field(default=None, max_length=200, description="emoji, iniciais ou URL de imagem")
    server_id: int | None = None
    is_admin: bool | None = None
    ativo: Literal[True] | None = Field(default=None, description="só reativa; para remover use DELETE")


class RemocaoClienteIn(BaseModel):
    senha: str | None = Field(default=None, description="obrigatória para remover a própria conta")


# ---------------------------------------------------------------- CRUD de servidores/nós (RF13)


class ServidorIn(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    host: str = Field(default="127.0.0.1", min_length=1, max_length=120)
    porta: int = Field(default=8000, ge=1, le=65535)
    regiao: str = Field(default="", max_length=60)
    capacidade: int = Field(default=100, ge=1, le=100_000)
    ativo: bool = True
    vizinhos: list[int] = Field(default_factory=list, max_length=100, description="ids dos nós ligados a este")


class ServidorOut(BaseModel):
    id: int
    nome: str
    host: str
    porta: int
    regiao: str
    capacidade: int
    ativo: bool
    vizinhos: list[int]
    clientes: list[str]


class StatusServidorIn(BaseModel):
    ativo: bool


class ClienteTopologia(BaseModel):
    username: str
    server_id: int | None
    online: bool


class TopologiaOut(BaseModel):
    nos: list[ServidorOut]
    clientes: list[ClienteTopologia]


# ---------------------------------------------------------------- painéis (Dashboard, Inspetor, Observador)


class EventoTransitoOut(BaseModel):
    """TraceEvent do servidor (GET /api/trace/{message_id}): só o que ele enxerga em trânsito."""

    etapa: str
    ator: str
    entrada: Any = None
    saida: Any = None
    duracao_ms: float
    ts: datetime


class EstatisticasOut(BaseModel):
    clientes: int
    online: int
    servidores: int
    servidores_ativos: int
    conversas: int
    mensagens: int
    envelopes_pendentes: int
    minhas_conversas: int
    minhas_mensagens: int


class AdulteracaoIn(BaseModel):
    ativo: bool = Field(description="o relay altera um bloco do próximo envelope (demonstração de assinatura inválida)")
