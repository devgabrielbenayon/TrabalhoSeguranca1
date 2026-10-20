"""Assinante do /ws/observer (RF15): guarda a topologia e os eventos de trânsito para o Painel Observador.

Mostra o que o SERVIDOR enxerga — metadados e envelopes cifrados. Nada aqui vem do keystore deste aparelho.
"""

from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from frontend.sessao import Sessao
from shared.schemas import TopologiaOut

log = logging.getLogger(__name__)

MAX_EVENTOS = 300


class ClienteObservador:
    def __init__(self, sessao: Sessao, ws_url: str) -> None:
        self.sessao = sessao
        self.ws_url = ws_url
        self.topologia: TopologiaOut | None = None
        self.eventos: dict[int, dict] = {}  # seq → evento (o histórico inicial pode chegar depois de um evento novo)
        self.adulteracao_armada = False
        self.versao = 0
        self._ws: ClientConnection | None = None
        self._tarefa: asyncio.Task | None = None
        sessao.ao_sair.append(self.desconectar)

    @property
    def conectado(self) -> bool:
        return self._ws is not None and self._tarefa is not None and not self._tarefa.done()

    def recentes(self, tipos: set[str] | None = None) -> list[dict]:
        """Do mais novo para o mais antigo."""
        return [e for _, e in sorted(self.eventos.items(), reverse=True) if tipos is None or e["type"] in tipos]

    def evento(self, message_id: str, para: str | None = None) -> dict | None:
        """Último trânsito de uma mensagem (para um destinatário, se informado)."""
        for e in self.recentes({"transito"}):
            if e["message_id"] == message_id and (para is None or e["para"] == para):
                return e
        return None

    async def conectar(self) -> None:
        if self.conectado:
            return
        self._ws = await connect(f"{self.ws_url}?token={self.sessao.api.token}")
        self._tarefa = asyncio.create_task(self._receber())

    async def desconectar(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._tarefa is not None:
            await asyncio.gather(self._tarefa, return_exceptions=True)
        self._ws = self._tarefa = None
        self.eventos.clear()
        self.topologia = None
        self._mudou()

    async def _receber(self) -> None:
        try:
            async for bruto in self._ws:
                try:
                    self._tratar(json.loads(bruto))
                except Exception:
                    log.exception("evento do observador inválido")
        except ConnectionClosed:
            pass
        finally:
            self._mudou()

    def _tratar(self, evento: dict) -> None:
        tipo = evento.get("type")
        if tipo == "topologia":
            self.topologia = TopologiaOut.model_validate(evento)
        elif tipo == "historico":
            for antigo in evento["eventos"]:
                self.eventos.setdefault(antigo["seq"], antigo)
        else:
            self.eventos[evento["seq"]] = evento
            if tipo == "adulteracao":
                self.adulteracao_armada = evento["ativo"]
            elif tipo == "transito" and evento.get("adulterado"):
                self.adulteracao_armada = False
            elif tipo == "conexao" and self.topologia is not None:
                for cliente in self.topologia.clientes:
                    if cliente.username == evento["usuario"]:
                        cliente.online = evento["online"]
        for seq in sorted(self.eventos)[:-MAX_EVENTOS]:
            del self.eventos[seq]
        self._mudou()

    def _mudou(self) -> None:
        self.versao += 1
