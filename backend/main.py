"""Back-end do CriptoChat RSA. Executar a partir da raiz: uvicorn backend.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI

from backend.api import auth, conversations, keys
from backend.db import URL_PADRAO, Base, criar_engine, criar_sessionmaker
from backend.ws import relay


def criar_app(url_banco: str = URL_PADRAO) -> FastAPI:
    app = FastAPI(title="CriptoChat RSA", description="Diretório de chaves públicas e relay de envelopes cifrados")

    engine = criar_engine(url_banco)
    Base.metadata.create_all(engine)
    app.state.sessionmaker = criar_sessionmaker(engine)
    app.state.relay = relay.Relay()

    app.include_router(auth.router)
    app.include_router(keys.router)
    app.include_router(conversations.router)
    app.include_router(relay.router)

    @app.get("/api/health", tags=["infra"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = criar_app()
