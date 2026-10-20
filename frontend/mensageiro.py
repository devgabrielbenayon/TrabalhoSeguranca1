"""Mensageiro do aparelho: WebSocket com o servidor, envio (fluxos 5.2 e 5.3) e recebimento.

Enviar: busca as públicas (cache) → monta um envelope por participante, inclusive a cópia → envia.
Receber: confere a assinatura com a pública do remetente → decifra com a própria privada → ack.
Se o canal cair sem ter sido fechado de propósito (servidor reiniciado, rede), reconecta sozinho.
Fica fora das páginas para poder ser testado sem UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from frontend.api_client import ErroApi
from frontend.key_cache import CacheChaves, ChaveSuspeita, SemChave
from frontend.keystore import ChaveNaoEncontrada
from frontend.sessao import Sessao
from shared.crypto.base import formatar_fingerprint
from shared.crypto.envelope import ErroEnvelope, abrir_envelope, montar_envelopes
from shared.schemas import ChavePublicaOut, ConversaOut, Envelope, Modo

log = logging.getLogger(__name__)

TEMPO_RESPOSTA = 15.0
ESPERA_MAXIMA_RECONEXAO = 10.0

StatusMensagem = Literal["enviando", "enviada", "entregue", "verificada", "rejeitada", "erro", "aviso"]
REMETENTE_SISTEMA = "sistema"  # avisos locais (troca/exclusão de chave), não vêm de ninguém


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
    sem_rota: set[str] = field(default_factory=set)  # destinatários sem caminho entre os nós (fila)
    envelopes: list[Envelope] = field(default_factory=list)  # o que foi enviado/recebido, para o Inspetor


@dataclass
class ConversaLocal:
    id: int
    tipo: str
    modo: Modo
    participantes: list[str]
    mensagens: dict[str, ItemMensagem] = field(default_factory=dict)
    nao_lidas: int = 0

    def ordenadas(self) -> list[ItemMensagem]:
        return sorted(self.mensagens.values(), key=lambda m: m.sent_at)

    def ultima(self) -> ItemMensagem | None:
        mensagens = [m for m in self.mensagens.values() if m.status != "aviso"]
        return max(mensagens, key=lambda m: m.sent_at) if mensagens else None


class Mensageiro:
    def __init__(self, sessao: Sessao, ws_url: str) -> None:
        self.sessao = sessao
        self.ws_url = ws_url
        self.cache = CacheChaves(sessao.api)
        self.conversas: dict[int, ConversaLocal] = {}
        self.versao = 0  # incrementa a cada mudança; a UI redesenha quando muda
        self.ouvintes: list[Callable[[], None]] = []
        self.sessao_expirada = False  # o servidor recusou o token ao reconectar (ex.: conta removida)
        self._ws: ClientConnection | None = None
        self._tarefa: asyncio.Task | None = None
        self._reconexao: asyncio.Task | None = None
        self._encerrando = False
        self._trava = asyncio.Lock()
        self._respostas: dict[str, asyncio.Future] = {}
        sessao.ao_sair.append(self.desconectar)

    @property
    def eu(self) -> str:
        return self.sessao.usuario.username

    @property
    def conectado(self) -> bool:
        return self._ws is not None and self._tarefa is not None and not self._tarefa.done()

    @property
    def reconectando(self) -> bool:
        return self._reconexao is not None and not self._reconexao.done()

    def mensagem(self, message_id: str) -> tuple[ConversaLocal, ItemMensagem] | None:
        for conversa in self.conversas.values():
            if message_id in conversa.mensagens:
                return conversa, conversa.mensagens[message_id]
        return None

    # ------------------------------------------------------------ conexão

    async def conectar(self) -> None:
        """Carrega conversas e histórico, depois abre o WebSocket (que entrega a fila offline).
        Se o servidor não responder, a reconexão segue tentando em segundo plano."""
        async with self._trava:
            if self.conectado:
                return
            self._encerrando = False
            self.sessao_expirada = False
            self.cache.conhecidas = self.sessao.keystore.contatos() if self.sessao.keystore else {}
            self.cache.ao_mudar = self._chave_mudou
            try:
                await self._sincronizar_e_abrir()
            except ErroApi as erro:
                if erro.status >= 500:
                    self._agendar_reconexao()
                raise
            except (OSError, httpx.HTTPError, InvalidHandshake, TimeoutError):
                self._agendar_reconexao()
                raise

    async def _sincronizar_e_abrir(self) -> None:
        for conversa in await self.sessao.api.conversas():
            self._adicionar_conversa(conversa)
        for conversa in list(self.conversas.values()):
            await self.carregar_historico(conversa.id)
        self._ws = await connect(f"{self.ws_url}?token={self.sessao.api.token}")
        self._tarefa = asyncio.create_task(self._receber())
        self._mudou()

    def _agendar_reconexao(self) -> None:
        if not self._encerrando and not self.reconectando:
            self._reconexao = asyncio.create_task(self._reconectar())

    async def desconectar(self) -> None:
        self._encerrando = True
        if self._reconexao is not None:
            self._reconexao.cancel()
            await asyncio.gather(self._reconexao, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()
        if self._tarefa is not None:
            await asyncio.gather(self._tarefa, return_exceptions=True)
        self._ws = self._tarefa = self._reconexao = None
        self.conversas.clear()
        self.cache = CacheChaves(self.sessao.api)
        self._mudou()

    async def _reconectar(self) -> None:
        """O canal caiu sem pedirmos: tenta de novo com espera crescente. A fila offline chega ao reabrir."""
        espera = 1.0
        while not self._encerrando and self.sessao.logado:
            await asyncio.sleep(espera)
            try:
                async with self._trava:
                    if self.conectado or self._encerrando:
                        return
                    await self._sincronizar_e_abrir()  # conversas e mensagens podem ter surgido enquanto estava fora
                    return
            except ErroApi as erro:
                if erro.status in (401, 403):  # o token não vale mais: só um novo login resolve
                    self.sessao_expirada = True
                    self._mudou()
                    return
            except (OSError, httpx.HTTPError, InvalidHandshake, TimeoutError):
                pass
            espera = min(espera * 2, ESPERA_MAXIMA_RECONEXAO)

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
            except (ErroApi, httpx.HTTPError) as erro:
                raise ErroEnvio("offline", f"não foi possível buscar as chaves: {erro}") from erro
            envelopes = montar_envelopes(
                texto, self.eu, privada, destinatarios, conversation_id, message_id=message_id, tracer=self.sessao.tracer
            )
            item.sent_at, item.envelopes = envelopes[0].sent_at, envelopes
            conversa.mensagens[message_id] = item
            self._mudou()

            try:
                resposta = await self._requisitar({
                    "type": "send",
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "envelopes": [e.para_json() for e in envelopes],
                })
            except ErroEnvio as erro:
                item.status, item.erro = "erro", erro.detail
                self._mudou()
                raise
            if resposta["type"] == "sent":
                item.status = "enviada"
                item.aguardando = set(outros)
                item.sem_rota = set(resposta.get("sem_rota", []))
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
        except ConnectionClosed as erro:
            raise ErroEnvio("offline", "a conexão caiu durante o envio") from erro
        except TimeoutError as erro:
            raise ErroEnvio("timeout", "o servidor não respondeu a tempo") from erro
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
            self._agendar_reconexao()
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
        elif tipo == "key_changed" and dados["user"] != self.eu:
            # descarta a chave antiga do cache; a nova é buscada (e conferida) no próximo envio
            self.cache.invalidar(dados["user"])
            self.cache.registrar_fingerprint(dados["user"], dados["modo"], dados["fingerprint"])
        elif tipo == "key_revoked" and dados["user"] != self.eu:
            self.cache.invalidar(dados["user"])
            self._avisar(
                dados["user"],
                dados["modo"],
                f"⛔ {dados['user']} excluiu a chave ({dados['modo']}). Não é possível enviar mensagens "
                "até que publique uma nova.",
            )
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
        item = ItemMensagem(
            envelope.message_id, envelope.from_, None, envelope.sent_at, "rejeitada", propria,
            key_id=envelope.from_key_id, envelopes=[envelope],
        )
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
            if confirmar and not propria:
                conversa.nao_lidas += 1
        self._mudou()
        if confirmar:
            await self._ack(envelope.message_id)  # confirma mesmo se rejeitada: não adianta reentregar

    async def _ack(self, message_id: str) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "ack", "message_id": message_id}))
            except ConnectionClosed:
                pass  # sem ack o servidor reentrega quando o canal voltar; o replay é ignorado

    def _marcar_entregue(self, message_id: str, destinatario: str) -> None:
        encontrada = self.mensagem(message_id)
        if encontrada is None or not encontrada[1].propria:
            return
        item = encontrada[1]
        item.aguardando.discard(destinatario)
        item.sem_rota.discard(destinatario)
        if not item.aguardando and item.status == "enviada":
            item.status = "entregue"
        self._mudou()

    # ------------------------------------------------------------ troca e exclusão de chave dos contatos

    def _chave_mudou(self, username: str, modo: str, anterior: str | None, novo: str) -> None:
        if self.sessao.keystore is not None:
            self.sessao.keystore.lembrar_contato(username, modo, novo)
        if anterior is not None and username != self.eu:
            self._avisar(
                username,
                modo,
                f"⚠ A chave de {username} mudou ({modo}). Novo fingerprint: {formatar_fingerprint(novo)}. "
                "Se não esperava por isso, confirme o número de segurança com a pessoa.",
            )

    def _avisar(self, username: str, modo: str, texto: str) -> None:
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for conversa in self.conversas.values():
            if username in conversa.participantes and conversa.modo == modo:
                aviso_id = f"aviso-{uuid.uuid4().hex}"
                conversa.mensagens[aviso_id] = ItemMensagem(aviso_id, REMETENTE_SISTEMA, texto, agora, "aviso", propria=False)
        self._mudou()

    def _mudou(self) -> None:
        self.versao += 1
        for ouvinte in list(self.ouvintes):
            ouvinte()
