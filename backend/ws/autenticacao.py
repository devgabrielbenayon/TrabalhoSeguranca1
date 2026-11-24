"""Autenticação dos canais WebSocket: o token vem na primeira mensagem, nunca na URL.

Na URL (`/ws?token=…`) ele ficaria gravado em logs de acesso, de proxies e no histórico do navegador.
Protocolo: o cliente abre o canal e envia `{"type": "auth", "token": "…"}`; o servidor responde
`{"type": "autenticado", …}` ou fecha com 4401 (token ausente, inválido ou demorado) / 4403 (sem permissão).
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, sessionmaker

from backend.auth import cliente_do_token
from backend.models import Client

FECHAMENTO_NAO_AUTORIZADO = 4401
FECHAMENTO_PROIBIDO = 4403

TEMPO_AUTENTICACAO_S = 10.0


async def autenticar(ws: WebSocket, fabrica: sessionmaker[Session]) -> Client | None:
    """Aceita o canal e espera o token. Devolve o cliente, ou None com o canal já fechado."""
    await ws.accept()
    try:
        dados = await asyncio.wait_for(ws.receive_json(), TEMPO_AUTENTICACAO_S)
    except WebSocketDisconnect:
        return None
    except (TimeoutError, ValueError, KeyError):
        dados = None

    token = dados.get("token") if isinstance(dados, dict) and dados.get("type") == "auth" else None
    cliente = None
    if isinstance(token, str) and token:
        with fabrica() as db:
            cliente = cliente_do_token(db, token)
    if cliente is None:
        await ws.close(code=FECHAMENTO_NAO_AUTORIZADO)
    return cliente
