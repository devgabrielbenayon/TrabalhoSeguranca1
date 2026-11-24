"""Canal /ws/observer (RF15): o que o servidor enxerga, ao vivo, para o Painel Observador.

Só administradores assinam: são os metadados de todos (quem fala com quem, quando, por onde, quanto)
e os envelopes cifrados. Texto claro nunca passa por aqui — o servidor não o tem.
"""

from __future__ import annotations

import itertools
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend import nos
from backend.ws.autenticacao import FECHAMENTO_NAO_AUTORIZADO, FECHAMENTO_PROIBIDO, autenticar

router = APIRouter()

__all__ = ["FECHAMENTO_NAO_AUTORIZADO", "FECHAMENTO_PROIBIDO", "Observador", "router"]


class Observador:
    def __init__(self, historico: int = 200) -> None:
        self._conexoes: set[WebSocket] = set()
        self._seq = itertools.count(1)
        self.recentes: deque[dict] = deque(maxlen=historico)

    @property
    def assinantes(self) -> int:
        return len(self._conexoes)

    async def publicar(self, evento: dict) -> None:
        # seq ordena e deduplica no painel (um evento pode chegar antes do histórico inicial)
        evento = {"seq": next(self._seq), "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **evento}
        if evento["type"] != "topologia":
            self.recentes.append(evento)
        for ws in list(self._conexoes):
            try:
                await ws.send_json(evento)
            except (RuntimeError, WebSocketDisconnect):
                self._conexoes.discard(ws)


@router.websocket("/ws/observer")
async def canal_observador(ws: WebSocket) -> None:
    observador: Observador = ws.app.state.observador
    cliente = await autenticar(ws, ws.app.state.sessionmaker)
    if cliente is None:
        return
    if not cliente.is_admin:
        await ws.close(code=FECHAMENTO_PROIBIDO)
        return
    with ws.app.state.sessionmaker() as db:
        topologia = nos.topologia(db, ws.app.state.relay.conectados())

    try:
        await ws.send_json({"type": "autenticado", "usuario": cliente.username})  # antes de qualquer evento
    except (RuntimeError, WebSocketDisconnect):
        return
    observador._conexoes.add(ws)
    try:
        await ws.send_json({"type": "topologia", **topologia.model_dump()})
        await ws.send_json({"type": "historico", "eventos": list(observador.recentes)})
        while True:
            await ws.receive_text()  # somente leitura: o que chegar é ignorado
    except WebSocketDisconnect:
        pass
    finally:
        observador._conexoes.discard(ws)
