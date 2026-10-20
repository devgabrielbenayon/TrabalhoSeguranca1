"""Relay de envelopes por WebSocket: valida, guarda só o cifrado, roteia pelos nós, entrega e mantém a fila.

O servidor não decifra nem verifica assinaturas: quem garante autoria e conteúdo é o destinatário.
Ele só confere o que consegue sem a privada de ninguém: quem envia, para quem e com qual key_id.
Cada passo vira um TraceEvent de trânsito e um evento do Observador.
"""

from __future__ import annotations

import base64
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend import chaves, nos, transito
from backend.auth import cliente_do_token
from backend.db import agora
from backend.models import Client, Conversation, EnvelopeRegistro, Message
from backend.ws.observer import FECHAMENTO_NAO_AUTORIZADO
from shared.schemas import AckWS, ChavePublicaOut, EnvioWS

if TYPE_CHECKING:
    from backend.ws.observer import Observador

router = APIRouter()

SEM_ROTA = "null"  # EnvelopeRegistro.hops de quem espera um caminho entre os nós ([] = relay central)


class Relay:
    """Conexões abertas por cliente (um usuário pode ter mais de uma aba/aparelho)."""

    def __init__(self) -> None:
        self._conexoes: dict[int, set[WebSocket]] = defaultdict(set)
        self.adulterar_proximo = False  # demonstração: o servidor altera um bloco do próximo envelope

    def adicionar(self, client_id: int, ws: WebSocket) -> None:
        self._conexoes[client_id].add(ws)

    def remover(self, client_id: int, ws: WebSocket) -> None:
        self._conexoes[client_id].discard(ws)
        if not self._conexoes[client_id]:
            del self._conexoes[client_id]

    def online(self, client_id: int) -> bool:
        return bool(self._conexoes.get(client_id))

    def conectados(self) -> set[int]:
        return {client_id for client_id, conexoes in self._conexoes.items() if conexoes}

    async def enviar(self, client_id: int, payload: dict) -> bool:
        entregue = False
        for ws in list(self._conexoes.get(client_id, ())):
            try:
                await ws.send_json(payload)
                entregue = True
            except (RuntimeError, WebSocketDisconnect):
                self.remover(client_id, ws)
        return entregue

    async def desconectar(self, client_id: int) -> None:
        """Fecha os canais de um cliente removido (o token dele já não vale)."""
        for ws in list(self._conexoes.get(client_id, ())):
            try:
                await ws.close(code=FECHAMENTO_NAO_AUTORIZADO)
            except RuntimeError:
                pass
            self.remover(client_id, ws)

    async def reentregar(self, fabrica: sessionmaker[Session], observador: Observador) -> None:
        """Depois de uma mudança na topologia: entrega a quem está online o que esperava por um caminho."""
        for client_id in self.conectados():
            with fabrica() as db:
                cliente = db.get(Client, client_id)
                fila = pendentes(db, cliente, so_sem_rota=True) if cliente is not None else []
            for entrega in fila:
                await _entregar(self, fabrica, observador, entrega, da_fila=True)


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
    caminho: list[str] | None  # None = sem caminho entre os nós agora (fica na fila)
    origem: str = transito.RELAY_CENTRAL  # nó onde o envelope espera enquanto não há caminho
    saltos_registrados: bool = False  # já passou pelos nós antes (estava na fila do nó do destinatário)


# ---------------------------------------------------------------- regras


def registrar_envio(db: Session, remetente: Client, envio: EnvioWS) -> list[Entrega]:
    """Valida, grava e calcula o caminho de cada envelope. Devolve as entregas aos outros participantes
    (a cópia do remetente fica só gravada)."""
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

    origem = _nome_no(remetente)
    db.add(Message(id=envio.message_id, conversation_id=conversa.id, sender_id=remetente.id, sent_at=envio.envelopes[0].sent_at))
    entregas = []
    for env in envio.envelopes:
        destinatario = membros[env.to]
        copia = destinatario.id == remetente.id
        caminho = [] if copia else nos.caminho(db, remetente.server_id, destinatario.server_id)
        db.add(EnvelopeRegistro(
            message_id=envio.message_id,
            recipient_id=destinatario.id,
            to_key_id=env.to_key_id,
            conteudo=env.model_dump_json(by_alias=True),
            status="entregue" if copia else "pendente",
            entregue_em=agora() if copia else None,
            hops=SEM_ROTA if caminho is None else json.dumps(caminho, ensure_ascii=False),
        ))
        if not copia:
            entregas.append(Entrega(destinatario.id, destinatario.username, env.para_json(), caminho, origem))
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


def pendentes(db: Session, destinatario: Client, so_sem_rota: bool = False) -> list[Entrega]:
    """Envelopes ainda não confirmados que podem ser entregues agora; os sem caminho continuam esperando.

    Quem já percorreu o caminho (destinatário estava offline) espera no nó dele e sai direto.
    `so_sem_rota`: só os que esperavam um caminho (os demais já foram entregues a quem está online).
    """
    consulta = select(EnvelopeRegistro).where(
        EnvelopeRegistro.recipient_id == destinatario.id, EnvelopeRegistro.status == "pendente"
    )
    if so_sem_rota:
        consulta = consulta.where(EnvelopeRegistro.hops == SEM_ROTA)
    entregas = []
    for registro in db.scalars(consulta.order_by(EnvelopeRegistro.id)).all():
        envelope = json.loads(registro.conteudo)
        if registro.hops != SEM_ROTA:
            entregas.append(Entrega(destinatario.id, destinatario.username, envelope, json.loads(registro.hops), saltos_registrados=True))
            continue
        remetente = db.get(Client, db.get(Message, registro.message_id).sender_id)
        # remetente removido: o envelope já está na rede, conta como saindo do nó do destinatário
        origem_id = remetente.server_id if remetente.ativo else destinatario.server_id
        caminho = nos.caminho(db, origem_id, destinatario.server_id)
        if caminho is not None:
            registro.hops = json.dumps(caminho, ensure_ascii=False)
            entregas.append(Entrega(destinatario.id, destinatario.username, envelope, caminho, _nome_no(remetente)))
    db.commit()
    return entregas


def _nome_no(cliente: Client) -> str:
    return cliente.servidor.nome if cliente.servidor is not None else transito.RELAY_CENTRAL


def _adulterar(envio: EnvioWS, remetente: str) -> str | None:
    """Servidor malicioso (demonstração): inverte um bit do 1º bloco do envelope de um destinatário.
    O destinatário detecta pela assinatura, que cobre todos os blocos."""
    for env in envio.envelopes:
        if env.to != remetente:
            bruto = bytearray(base64.b64decode(env.blocks[0]))
            bruto[-1] ^= 0x01
            env.blocks[0] = base64.b64encode(bytes(bruto)).decode("ascii")
            return env.to
    return None


async def _entregar(relay: Relay, fabrica: sessionmaker[Session], observador: Observador, entrega: Entrega, **extra) -> str:
    """Tenta entregar agora; registra os saltos, o desfecho e avisa o Observador. Devolve o status."""
    if entrega.caminho is None:
        status = "sem_rota"
    elif await relay.enviar(entrega.client_id, {"type": "message", "envelope": entrega.envelope}):
        status = "entregue"
    else:
        status = "offline"
    with fabrica() as db:
        if entrega.caminho and not entrega.saltos_registrados:
            transito.registrar_saltos(db, entrega.envelope, entrega.caminho)
        ator = entrega.caminho[-1] if entrega.caminho else entrega.origem
        transito.registrar_desfecho(db, entrega.envelope, ator, status)
        db.commit()
    await observador.publicar(transito.evento_transito(entrega.envelope, entrega.caminho, status, **extra))
    return status


# ---------------------------------------------------------------- canal


@router.websocket("/ws")
async def canal(ws: WebSocket, token: str = "") -> None:
    relay: Relay = ws.app.state.relay
    observador: Observador = ws.app.state.observador
    fabrica: sessionmaker[Session] = ws.app.state.sessionmaker

    with fabrica() as db:
        cliente = cliente_do_token(db, token)
    if cliente is None:
        await ws.close(code=FECHAMENTO_NAO_AUTORIZADO)
        return

    await ws.accept()
    relay.adicionar(cliente.id, ws)
    await observador.publicar({"type": "conexao", "usuario": cliente.username, "online": True})
    try:
        # fila offline: tudo que chegou enquanto o cliente estava desconectado (e já tem caminho)
        with fabrica() as db:
            fila = pendentes(db, db.get(Client, cliente.id))
        for entrega in fila:
            await _entregar(relay, fabrica, observador, entrega, da_fila=True)

        while True:
            try:
                dados = await ws.receive_json()
            except (json.JSONDecodeError, KeyError):
                await ws.send_json(ErroProtocolo("invalid", "mensagem não é JSON").payload(None))
                continue
            await _processar(ws, relay, observador, fabrica, cliente.id, dados)
    except WebSocketDisconnect:
        pass
    finally:
        relay.remover(cliente.id, ws)
        if not relay.online(cliente.id):
            await observador.publicar({"type": "conexao", "usuario": cliente.username, "online": False})


async def _processar(
    ws: WebSocket, relay: Relay, observador: Observador, fabrica: sessionmaker[Session], client_id: int, dados: dict
) -> None:
    tipo = dados.get("type") if isinstance(dados, dict) else None
    message_id = dados.get("message_id") if isinstance(dados, dict) else None

    with fabrica() as db:
        # relido a cada mensagem: o cliente pode ter sido removido ou mudado de nó com o canal aberto
        eu = db.get(Client, client_id)
        if eu is None or not eu.ativo:
            await ws.close(code=FECHAMENTO_NAO_AUTORIZADO)
            raise WebSocketDisconnect(FECHAMENTO_NAO_AUTORIZADO)
        username = eu.username

        if tipo == "send":
            inicio = time.perf_counter()
            try:
                envio = EnvioWS.model_validate(dados)
                adulterado = _adulterar(envio, username) if relay.adulterar_proximo else None
                entregas = registrar_envio(db, eu, envio)
            except ValidationError as erro:
                await ws.send_json(ErroProtocolo("invalid", erro.errors(include_url=False)[0]["msg"]).payload(message_id))
                return
            except ErroProtocolo as erro:
                await ws.send_json(erro.payload(message_id))
                await observador.publicar(
                    {"type": "recusado", "message_id": message_id, "de": username, "code": erro.code, "detail": erro.detail}
                )
                return
            if adulterado is not None:
                relay.adulterar_proximo = False
            transito.registrar(
                db, envio.message_id, "recebido", _nome_no(eu),
                {"de": username, "envelopes": len(envio.envelopes), "para": [e.to for e in envio.envelopes]},
                "validado: remetente, key_ids e limites; só o cifrado foi gravado",
                (time.perf_counter() - inicio) * 1000,
            )
            db.commit()

        elif tipo == "ack":
            try:
                ack = AckWS.model_validate(dados)
            except ValidationError:
                await ws.send_json(ErroProtocolo("invalid", "ack inválido").payload(message_id))
                return
            remetente_id = marcar_entregue(db, eu, ack.message_id)
            if remetente_id is not None:
                transito.registrar(db, ack.message_id, "confirmado", _nome_no(eu), {"por": username}, "entrega confirmada")
                db.commit()

        else:
            await ws.send_json(ErroProtocolo("unknown_type", f"tipo desconhecido: {tipo}").payload(message_id))
            return

    if tipo == "send":
        offline, sem_rota = [], []
        for entrega in entregas:
            extra = {"adulterado": True} if entrega.username == adulterado else {}
            status = await _entregar(relay, fabrica, observador, entrega, **extra)
            if status == "offline":
                offline.append(entrega.username)
            elif status == "sem_rota":
                sem_rota.append(entrega.username)
        await ws.send_json({"type": "sent", "message_id": envio.message_id, "offline": offline, "sem_rota": sem_rota})
    elif remetente_id is not None:
        await relay.enviar(remetente_id, {"type": "delivered", "message_id": ack.message_id, "to": username})
        await observador.publicar({"type": "confirmado", "message_id": ack.message_id, "por": username})
