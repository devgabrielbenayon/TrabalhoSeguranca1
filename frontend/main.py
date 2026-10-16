"""App cliente do CriptoChat RSA. Executar a partir da raiz: python -m frontend.main

Cada processo deste app representa o aparelho de um usuário: a chave privada fica só aqui.
Para simular dois aparelhos, suba dois processos com CRIPTOCHAT_PORTA diferentes.
"""

import os

from nicegui import ui

from frontend.api_client import ApiCliente
from frontend.pages import conta
from frontend.sessao import Sessao

API_URL = os.environ.get("CRIPTOCHAT_API", "http://127.0.0.1:8000")
PORTA = int(os.environ.get("CRIPTOCHAT_PORTA", "8080"))
HOST = os.environ.get("CRIPTOCHAT_HOST", "127.0.0.1")  # 0.0.0.0 para abrir na rede local (Docker)

sessao = Sessao(ApiCliente(API_URL))
conta.registrar_paginas(sessao)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title=f"CriptoChat RSA :{PORTA}", host=HOST, port=PORTA, reload=False, show=False)
