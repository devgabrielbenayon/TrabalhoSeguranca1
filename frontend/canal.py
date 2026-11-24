"""Abertura autenticada dos canais WebSocket (/ws e /ws/observer).

O token vai na primeira mensagem, não na URL (ver backend/ws/autenticacao.py). Recusa do servidor vira
ErroApi 401/403, o mesmo erro das rotas HTTP, para a reconexão tratar tudo do mesmo jeito.
"""

from __future__ import annotations

import asyncio
import json
import ssl

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from frontend.api_client import ErroApi

TEMPO_AUTENTICACAO_S = 15.0
FECHAMENTO_PROIBIDO = 4403


async def abrir_canal(url: str, token: str | None, tls: ssl.SSLContext | None = None) -> ClientConnection:
    extras = {"ssl": tls} if url.startswith("wss://") and tls is not None else {}
    ws = await connect(url, **extras)
    try:
        await ws.send(json.dumps({"type": "auth", "token": token or ""}))
        resposta = json.loads(await asyncio.wait_for(ws.recv(), TEMPO_AUTENTICACAO_S))
    except ConnectionClosed as erro:
        codigo = erro.rcvd.code if erro.rcvd is not None else None
        if codigo == FECHAMENTO_PROIBIDO:
            raise ErroApi(403, "o canal exige permissão de administrador") from erro
        raise ErroApi(401, "o servidor recusou o token do canal") from erro
    except BaseException:
        await ws.close()
        raise
    if not isinstance(resposta, dict) or resposta.get("type") != "autenticado":
        await ws.close()
        raise ErroApi(401, "o servidor não confirmou a autenticação do canal")
    return ws
