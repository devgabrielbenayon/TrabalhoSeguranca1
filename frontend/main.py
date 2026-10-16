"""App cliente do CriptoChat RSA. Executar a partir da raiz: python -m frontend.main

Cada processo deste app representa o aparelho de um usuário: a chave privada fica só aqui.
"""

import os

import httpx
from nicegui import ui

API_URL = os.environ.get("CRIPTOCHAT_API", "http://127.0.0.1:8000")
PORTA = int(os.environ.get("CRIPTOCHAT_PORTA", "8080"))


@ui.page("/")
async def inicio() -> None:
    ui.label("CriptoChat RSA").classes("text-2xl font-bold")
    status = ui.label("Verificando servidor…")
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=3) as cliente:
            resposta = await cliente.get("/api/health")
            resposta.raise_for_status()
        status.text = f"Servidor {API_URL}: {resposta.json()['status']}"
    except httpx.HTTPError as erro:
        status.text = f"Servidor {API_URL} indisponível ({erro.__class__.__name__})"


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="CriptoChat RSA", port=PORTA, reload=False, show=False)
