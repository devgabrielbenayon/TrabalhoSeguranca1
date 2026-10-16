"""Relay de envelopes por WebSocket: valida, guarda só o cifrado, entrega e mantém a fila offline.

O servidor não decifra nem verifica assinaturas: quem garante autoria e conteúdo é o destinatário.
Ele só confere o que consegue sem a privada de ninguém: quem envia, para quem e com qual key_id.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend import chaves
from backend.auth import cliente_do_token
from backend.db import agora
from backend.models import Client, Conversation, EnvelopeRegistro, Message
from shared.schemas import AckWS, ChavePublicaOut, EnvioWS

router = APIRouter()

FECHAMENTO_NAO_AUTORIZADO = 4401


class Relay:
    """Conexões abertas por cliente (um usuário pode ter mais de uma aba/aparelho)."""

    def __init__(self) -> None:
        self._conexoes: dict[int, set[WebSocket]] = defaultdict(set)

    def adicionar(self, client_id: int, ws: WebSocket) -> None:
        self._conexoes[client_id].add(ws)

    def remover(self, client_id: int, ws: WebSocket) -> None:
        self._conexoes[client_id].discard(ws)
        if not self._conexoes[client_id]:
            del self._conexoes[client_id]

    def online(self, client_id: int) -> bool:
        return bool(self._conexoes.get(client_id))

    async def enviar(self, client_id: int, payload: dict) -> bool:
        entregue = False
        for ws in list(self._conexoes.get(client_id, ())):
            try:
                await ws.send_json(payload)
                entregue = True
            except (RuntimeError, WebSocketDisconnect):
                self.remover(client_id, ws)
        return entregue


@dataclass
class ErroProtocolo(Exception):
    code: str
    detail: str
    extra: dict = field(default_factory=dict)

    def payload(self, message_id: str | None) -> dict:
        return {"type": "error", "code": self.code, "detail": self.detail, "message_id": message_id, **self.extra}


@dataclass
class Entrega:
    client_id: int
    username: str
    envelope: dict


# ---------------------------------------------------------------- regras


def registrar_envio(db: Session, remetente: Client, envio: EnvioWS) -> list[Entrega]:
    """Valida e grava a mensagem. Devolve as entregas aos outros participantes (a cópia do remetente fica só gravada)."""
    conversa = db.get(Conversation, envio.conversation_id)
    if conversa is None:
        raise ErroProtocolo("unknown_conversation", "conversa inexistente")
    membros = {m.username: m for m in conversa.membros}
    if remetente.username not in membros:
        raise ErroProtocolo("not_participant", "você não participa desta conversa")
    if db.get(Message, envio.message_id) is not None:
        raise ErroProtocolo("duplicate", "message_id já usado")

    destinos = [e.to for e in envio.envelopes]
    if len(destinos) != len(set(destinos)) or set(destinos) != set(membros):
        raise ErroProtocolo(
            "wrong_recipients",
            "é preciso exatamente um envelope por participante, inclusive a cópia do remetente",
            {"participantes": sorted(membros)},
        )

    ativa_remetente = chaves.chave_ativa(db, remetente.id, conversa.modo)
    for env in envio.envelopes:
        if env.message_id != envio.message_id or env.conversation_id != conversa.id:
            raise ErroProtocolo("inconsistent", "envelope com message_id ou conversa diferente do envio")
        if env.from_ != remetente.username:
            raise ErroProtocolo("bad_sender", "o remetente do envelope não é o dono do token")
        if env.mode != conversa.modo:
            raise ErroProtocolo("wrong_mode", f"a conversa é do modo {conversa.modo}")
        if ativa_remetente is None or env.from_key_id != ativa_remetente.key_id:
            raise ErroProtocolo("sender_key_outdated", "o envelope não foi assinado com a sua chave ativa")

    desatualizadas: dict[str, ChavePublicaOut] = {}
    sem_chave: list[str] = []
    for env in envio.envelopes:
        ativa = chaves.chave_ativa(db, membros[env.to].id, conversa.modo)
        if ativa is None:
            sem_chave.append(env.to)
        elif ativa.key_id != env.to_key_id:
            desatualizadas[env.to] = chaves.para_saida(ativa)
    if sem_chave:
        raise ErroProtocolo("recipient_without_key", f"sem chave ativa: {', '.join(sem_chave)}", {"usuarios": sem_chave})
    if desatualizadas:
        raise ErroProtocolo(
            "key_outdated",
            f"chave desatualizada para: {', '.join(desatualizadas)}",
            {"chaves": {u: c.model_dump(mode="json") for u, c in desatualizadas.items()}},
        )

    db.add(Message(id=envio.message_id, conversation_id=conversa.id, sender_id=remetente.id, sent_at=envio.envelopes[0].sent_at))
    entregas = []
    for env in envio.envelopes:
        destinatario = membros[env.to]
        copia = destinatario.id == remetente.id
        db.add(EnvelopeRegistro(
            message_id=envio.message_id,
            recipient_id=destinatario.id,
            to_key_id=env.to_key_id,
            conteudo=env.model_dump_json(by_alias=True),
            status="entregue" if copia else "pendente",
            entregue_em=agora() if copia else None,
        ))
        if not copia:
            entregas.append(Entrega(destinatario.id, destinatario.username, env.para_json()))
    db.commit()
    return entregas


def marcar_entregue(db: Session, destinatario: Client, message_id: str) -> int | None:
    """Confirma a entrega. Devolve o id do remetente para avisá-lo, ou None se não havia o que confirmar."""
    registro = db.scalar(
        select(EnvelopeRegistro).where(
            EnvelopeRegistro.message_id == message_id,
            EnvelopeRegistro.recipient_id == destinatario.id,
            EnvelopeRegistro.status == "pendente",
        )
    )
    if registro is None:
        return None
    registro.status, registro.entregue_em = "entregue", agora()
    db.commit()
    return db.get(Message, message_id).sender_id


def pendentes(db: Session, destinatario: Client) -> list[dict]:
    registros = db.scalars(
        select(EnvelopeRegistro)
        .where(EnvelopeRegistro.recipient_id == destinatario.id, EnvelopeRegistro.status == "pendente")
        .order_by(EnvelopeRegistro.id)
    ).all()
    return [json.loads(r.conteudo) for r in registros]


# ---------------------------------------------------------------- canal


@router.websocket("/ws")
async def canal(ws: WebSocket, token: str = "") -> None:
    relay: Relay = ws.app.state.relay
    fabrica: sessionmaker[Session] = ws.app.state.sessionmaker

    with fabrica() as db:
        cliente = cliente_do_token(db, token)
    if cliente is None:
        await ws.close(code=FECHAMENTO_NAO_AUTORIZADO)
        return

    await ws.accept()
    relay.adicionar(cliente.id, ws)
    try:
        # fila offline: tudo que chegou enquanto o cliente estava desconectado
        with fabrica() as db:
            for envelope in pendentes(db, cliente):
                await ws.send_json({"type": "message", "envelope": envelope})

        while True:
            try:
                dados = await ws.receive_json()
            except (json.JSONDecodeError, KeyError):
                await ws.send_json(ErroProtocolo("invalid", "mensagem não é JSON").payload(None))
                continue
            await _processar(ws, relay, fabrica, cliente, dados)
    except WebSocketDisconnect:
        pass
    finally:
        relay.remover(cliente.id, ws)


async def _processar(ws: WebSocket, relay: Relay, fabrica: sessionmaker[Session], cliente: Client, dados: dict) -> None:
    tipo = dados.get("type") if isinstance(dados, dict) else None
    message_id = dados.get("message_id") if isinstance(dados, dict) else None

    if tipo == "send":
        try:
            envio = EnvioWS.model_validate(dados)
            with fabrica() as db:
                entregas = registrar_envio(db, db.merge(cliente), envio)
        except ValidationError as erro:
            await ws.send_json(ErroProtocolo("invalid", erro.errors(include_url=False)[0]["msg"]).payload(message_id))
            return
        except ErroProtocolo as erro:
            await ws.send_json(erro.payload(message_id))
            return
        offline = []
        for entrega in entregas:
            if not await relay.enviar(entrega.client_id, {"type": "message", "envelope": entrega.envelope}):
                offline.append(entrega.username)
        await ws.send_json({"type": "sent", "message_id": envio.message_id, "offline": offline})

    elif tipo == "ack":
        try:
            ack = AckWS.model_validate(dados)
        except ValidationError:
            await ws.send_json(ErroProtocolo("invalid", "ack inválido").payload(message_id))
            return
        with fabrica() as db:
            remetente_id = marcar_entregue(db, db.merge(cliente), ack.message_id)
        if remetente_id is not None:
            await relay.enviar(remetente_id, {"type": "delivered", "message_id": ack.message_id, "to": cliente.username})

    else:
        await ws.send_json(ErroProtocolo("unknown_type", f"tipo desconhecido: {tipo}").payload(message_id))
