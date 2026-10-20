"""Back-end do CriptoChat RSA. Executar a partir da raiz: uvicorn backend.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import select

from backend import nos
from backend.api import auth, clients, conversations, keys, painel, servers
from backend.db import URL_PADRAO, criar_engine, criar_sessionmaker, criar_tabelas
from backend.models import Client, Server
from backend.ws import observer, relay


def criar_app(url_banco: str = URL_PADRAO, topologia_exemplo: bool = True) -> FastAPI:
    """`topologia_exemplo`: num banco novo, cria os nós de demonstração (Manaus, São Paulo, Brasília, Recife)."""
    app = FastAPI(title="CriptoChat RSA", description="Diretório de chaves públicas e relay de envelopes cifrados")

    engine = criar_engine(url_banco)
    criar_tabelas(engine)
    app.state.sessionmaker = criar_sessionmaker(engine)
    app.state.relay = relay.Relay()
    app.state.observador = observer.Observador()

    if topologia_exemplo:
        with app.state.sessionmaker() as db:
            if db.scalar(select(Server.id).limit(1)) is None and db.scalar(select(Client.id).limit(1)) is None:
                nos.criar_topologia_exemplo(db)
                db.commit()

    app.include_router(auth.router)
    app.include_router(keys.router)
    app.include_router(clients.router)
    app.include_router(servers.router)
    app.include_router(conversations.router)
    app.include_router(painel.router)
    app.include_router(relay.router)
    app.include_router(observer.router)

    @app.get("/api/health", tags=["infra"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = criar_app()
