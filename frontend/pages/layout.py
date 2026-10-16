"""Elementos comuns às telas."""

from __future__ import annotations

from nicegui import ui

from frontend.api_client import ErroApi
from frontend.sessao import Sessao


def cabecalho(sessao: Sessao) -> None:
    with ui.header().classes("items-center justify-between bg-teal-800"):
        ui.link("CriptoChat RSA", "/").classes("text-lg font-bold text-white no-underline")
        with ui.row().classes("items-center gap-4"):
            if sessao.logado:
                ui.link("Chat", "/chat").classes("text-white")
                ui.link("Minhas chaves", "/").classes("text-white")
                ui.label(f"@{sessao.usuario.username}").classes("text-white")

                async def sair() -> None:
                    await sessao.sair()
                    ui.navigate.to("/login")

                ui.button("Sair", on_click=sair).props("flat color=white")
            else:
                ui.link("Entrar", "/login").classes("text-white")
                ui.link("Criar conta", "/cadastro").classes("text-white")


def mensagem_erro(erro: Exception) -> str:
    if isinstance(erro, ErroApi) and isinstance(erro.detalhe, list):  # erros de validação do Pydantic
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in erro.detalhe)
    if isinstance(erro, ErroApi):
        return str(erro.detalhe)
    return str(erro)
