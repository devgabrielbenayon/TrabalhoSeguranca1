"""Mensageiro do aparelho: WebSocket com o servidor, envio (fluxos 5.2 e 5.3) e recebimento.

Enviar: busca as públicas (cache) → monta um envelope por participante, inclusive a cópia → envia.
Receber: confere a assinatura com a pública do remetente → decifra com a própria privada → ack.
Fica fora das páginas para poder ser testado sem UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from frontend.key_cache import CacheChaves, ChaveSuspeita, SemChave
from frontend.keystore import ChaveNaoEncontrada
from frontend.sessao import Sessao
from shared.crypto.envelope import ErroEnvelope, abrir_envelope, montar_envelopes
from shared.schemas import ChavePublicaOut, ConversaOut, Envelope, Modo

log = logging.getLogger(__name__)

TEMPO_RESPOSTA = 15.0

StatusMensagem = Literal["enviando", "enviada", "entregue", "verificada", "rejeitada", "erro"]


class ErroEnvio(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class ItemMensagem:
    message_id: str
    remetente: str
    texto: str | None
    sent_at: str
    status: StatusMensagem
    propria: bool
    erro: str | None = None
    key_id: str | None = None  # chave do remetente usada na assinatura
    aguardando: set[str] = field(default_factory=set)  # destinatários que ainda não confirmaram


@dataclass
class ConversaLocal:
    id: int
    tipo: str
    modo: Modo
    participantes: list[str]
    mensagens: dict[str, ItemMensagem] = field(default_factory=dict)

    def ordenadas(self) -> list[ItemMensagem]:
        return sorted(self.mensagens.values(), key=lambda m: m.sent_at)


class Mensageiro:
    def __init__(self, sessao: Sessao, ws_url: str) -> None:
        self.sessao = sessao
        self.ws_url = ws_url
        self.cache = CacheChaves(sessao.api)
        self.conversas: dict[int, ConversaLocal] = {}
        self.versao = 0  # incrementa a cada mudança; a UI redesenha quando muda
        self.ouvintes: list[Callable[[], None]] = []
        self._ws: ClientConnection | None = None
        self._tarefa: asyncio.Task | None = None
        self._respostas: dict[str, asyncio.Future] = {}
        sessao.ao_sair.append(self.desconectar)

    @property
    def eu(self) -> str:
        return self.sessao.usuario.username

    @property
    def conectado(self) -> bool:
        return self._ws is not None and self._tarefa is not None and not self._tarefa.done()

    # ------------------------------------------------------------ conexão

    async def conectar(self) -> None:
        """Carrega conversas e histórico, depois abre o WebSocket (que entrega a fila offline)."""
        if self.conectado:
            return
        for conversa in await self.sessao.api.conversas():
            self._adicionar_conversa(conversa)
        for conversa in list(self.conversas.values()):
            await self.carregar_historico(conversa.id)
        self._ws = await connect(f"{self.ws_url}?token={self.sessao.api.token}")
        self._tarefa = asyncio.create_task(self._receber())

    async def desconectar(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._tarefa is not None:
            await asyncio.gather(self._tarefa, return_exceptions=True)
        self._ws = self._tarefa = None
        self.conversas.clear()
        self.cache = CacheChaves(self.sessao.api)
        self._mudou()

    async def carregar_historico(self, conversation_id: int) -> None:
        for envelope in await self.sessao.api.historico(conversation_id):
            await self._abrir(envelope, confirmar=False)

    # ------------------------------------------------------------ conversas

    async def nova_conversa(self, participantes: list[str], modo: Modo) -> ConversaLocal:
        return self._adicionar_conversa(await self.sessao.api.criar_conversa(participantes, modo))

    def _adicionar_conversa(self, conversa: ConversaOut) -> ConversaLocal:
        if conversa.id not in self.conversas:
            self.conversas[conversa.id] = ConversaLocal(conversa.id, conversa.tipo, conversa.modo, conversa.participantes)
            self._mudou()
        return self.conversas[conversa.id]

    # ------------------------------------------------------------ envio (passo 2)

    async def enviar(self, conversation_id: int, texto: str) -> ItemMensagem:
        conversa = self.conversas[conversation_id]
        privada = self.sessao.keystore.ativa(conversa.modo) if self.sessao.keystore else None
        if privada is None:
            raise ErroEnvio("no_private_key", f"este aparelho não tem sua chave privada do modo {conversa.modo}")
        outros = [p for p in conversa.participantes if p != self.eu]
        message_id = uuid.uuid4().hex
        item = ItemMensagem(message_id, self.eu, texto, "", "enviando", propria=True, key_id=privada.publica.key_id)

        for tentativa in range(2):
            try:
                destinatarios = await self.cache.obter(outros, conversa.modo)
            except (SemChave, ChaveSuspeita) as erro:
                raise ErroEnvio("keys", str(erro)) from erro
            envelopes = montar_envelopes(
                texto, self.eu, privada, destinatarios, conversation_id, message_id=message_id, tracer=self.sessao.tracer
            )
            item.sent_at = envelopes[0].sent_at
            conversa.mensagens[message_id] = item
            self._mudou()

            resposta = await self._requisitar({
                "type": "send",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "envelopes": [e.para_json() for e in envelopes],
            })
            if resposta["type"] == "sent":
                item.status = "enviada"
                item.aguardando = set(outros)
                self._mudou()
                return item
            if resposta.get("code") == "key_outdated" and tentativa == 0:
                # o servidor devolveu as chaves atuais: atualiza o cache e cifra de novo
                for username, chave in resposta["chaves"].items():
                    self.cache.invalidar(username)
                    try:
                        self.cache.guardar(username, ChavePublicaOut.model_validate(chave))
                    except ChaveSuspeita as erro:
                        raise ErroEnvio("keys", str(erro)) from erro
                continue
            item.status, item.erro = "erro", resposta.get("detail")
            self._mudou()
            raise ErroEnvio(resposta.get("code", "erro"), resposta.get("detail", ""))
        raise AssertionError("inalcançável")

    async def _requisitar(self, payload: dict) -> dict:
        if not self.conectado:
            raise ErroEnvio("offline", "sem conexão com o servidor")
        futuro = asyncio.get_running_loop().create_future()
        self._respostas[payload["message_id"]] = futuro
        try:
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(futuro, TEMPO_RESPOSTA)
        finally:
            self._respostas.pop(payload["message_id"], None)

    # ------------------------------------------------------------ recebimento

    async def _receber(self) -> None:
        try:
            async for bruto in self._ws:
                try:
                    await self._tratar(json.loads(bruto))
                except Exception:  # uma mensagem ruim não pode derrubar o canal
                    log.exception("falha ao tratar mensagem do servidor")
        except ConnectionClosed:
            pass
        finally:
            for futuro in self._respostas.values():
                if not futuro.done():
                    futuro.set_result({"type": "error", "code": "offline", "detail": "conexão encerrada"})
            self._mudou()

    async def _tratar(self, dados: dict) -> None:
        tipo = dados.get("type")
        if tipo in ("sent", "error") and dados.get("message_id") in self._respostas:
            self._respostas[dados["message_id"]].set_result(dados)
        elif tipo == "message":
            await self._abrir(Envelope.model_validate(dados["envelope"]), confirmar=True)
        elif tipo == "delivered":
            self._marcar_entregue(dados["message_id"], dados["to"])
        elif tipo == "conversation":
            self._adicionar_conversa(ConversaOut.model_validate(dados["conversation"]))
        elif tipo == "error":
            log.warning("erro do servidor: %s", dados)

    async def _abrir(self, envelope: Envelope, confirmar: bool) -> None:
        conversa = self.conversas.get(envelope.conversation_id)
        if conversa is None:  # conversa criada enquanto estávamos offline
            for c in await self.sessao.api.conversas():
                self._adicionar_conversa(c)
            conversa = self.conversas.get(envelope.conversation_id)
        if conversa is not None and envelope.message_id in conversa.mensagens:
            item = conversa.mensagens[envelope.message_id]
            if item.status in ("verificada", "enviada", "entregue"):  # replay ou reentrega: só confirma
                if confirmar:
                    await self._ack(envelope.message_id)
                return

        propria = envelope.from_ == self.eu
        item = ItemMensagem(envelope.message_id, envelope.from_, None, envelope.sent_at, "rejeitada", propria, key_id=envelope.from_key_id)
        try:
            privada = self.sessao.keystore.carregar(envelope.to_key_id)
            publica_remetente = await self.cache.por_id(envelope.from_, envelope.from_key_id)
            aberta = abrir_envelope(envelope, privada, publica_remetente, tracer=self.sessao.tracer)
            item.texto = aberta.texto
            item.status = "enviada" if propria else "verificada"
        except ChaveNaoEncontrada:
            item.erro = "a chave privada desta mensagem não está neste aparelho"
        except (ErroEnvelope, ChaveSuspeita) as erro:
            item.erro = f"{type(erro).__name__}: {erro}"
        except Exception as erro:  # chave do remetente inacessível, etc.
            item.erro = f"não foi possível verificar: {erro}"

        if conversa is not None:
            conversa.mensagens[envelope.message_id] = item
        self._mudou()
        if confirmar:
            await self._ack(envelope.message_id)  # confirma mesmo se rejeitada: não adianta reentregar

    async def _ack(self, message_id: str) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "ack", "message_id": message_id}))

    def _marcar_entregue(self, message_id: str, destinatario: str) -> None:
        for conversa in self.conversas.values():
            item = conversa.mensagens.get(message_id)
            if item is not None and item.propria:
                item.aguardando.discard(destinatario)
                if not item.aguardando and item.status == "enviada":
                    item.status = "entregue"
                self._mudou()

    def _mudou(self) -> None:
        self.versao += 1
        for ouvinte in list(self.ouvintes):
            ouvinte()
