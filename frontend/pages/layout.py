"""Moldura comum às telas: cabeçalho, menu lateral e pequenos componentes visuais."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import httpx
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.sessao import Sessao

if TYPE_CHECKING:
    from frontend.mensageiro import Mensageiro

CORES = {
    "primary": "#0f766e",
    "secondary": "#334155",
    "accent": "#b45309",
    "positive": "#15803d",
    "negative": "#b91c1c",
    "warning": "#b45309",
    "info": "#0369a1",
}
PALETA_AVATAR = ("#0f766e", "#7c3aed", "#b45309", "#0369a1", "#be185d", "#4d7c0f", "#9f1239", "#155e75")
COR_MODO = {"real": "teal", "didatico": "orange"}
NOME_MODO = {"real": "real", "didatico": "didático"}
NOME_CHAVE = {"real": "chave real", "didatico": "chave didática"}

# (rota, rótulo, ícone, só administradores)
MENU = (
    ("/", "Início", "space_dashboard", False),
    ("/chat", "Chat", "forum", False),
    ("/chaves", "Minhas chaves", "vpn_key", False),
    ("/inspetor", "Inspetor", "biotech", False),
    ("/observador", "Observador", "hub", True),
    ("/clientes", "Clientes", "group", False),
    ("/servidores", "Servidores", "dns", False),
    ("/laboratorio", "Laboratório", "science", False),
)


def moldura(sessao: Sessao, mensageiro: Mensageiro | None = None, ativa: str = "") -> ui.column:
    """Cabeçalho + menu (quando logado). Devolve a coluna onde a página põe o conteúdo."""
    ui.colors(**CORES)
    ui.query("body").classes("bg-slate-100")
    # entrada escalonada (animação feita no navegador): style="animation-delay: …" em cada elemento .surgir
    ui.add_css("@keyframes surgir {from {opacity: 0; transform: translateY(8px)} to {opacity: 1; transform: none}}"
               ".surgir {animation: surgir .45s ease both}"
               ".q-timeline__title {font-size: .95rem; font-weight: 600; margin-bottom: 2px}"
               ".q-timeline__subtitle {font-size: .7rem}"
               ".q-timeline--dense .q-timeline__content {padding-bottom: 12px}")
    gaveta: ui.left_drawer | None = None

    with ui.header(elevated=True).classes("items-center justify-between bg-teal-900 px-4 py-2"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            if sessao.logado:
                ui.button(icon="menu", on_click=lambda: gaveta.toggle()).props("flat round dense color=white")
            ui.icon("enhanced_encryption", color="white").classes("text-2xl")
            ui.link("CriptoChat RSA", "/").classes("text-lg font-bold text-white no-underline tracking-wide")
        with ui.row().classes("items-center gap-3 no-wrap"):
            if sessao.logado:
                if mensageiro is not None:
                    _indicador_conexao(sessao, mensageiro)
                with ui.row().classes("items-center gap-2 no-wrap"):
                    avatar(sessao.usuario.username, sessao.usuario.avatar, tamanho=8)
                    ui.label(f"@{sessao.usuario.username}").classes("text-white font-medium max-sm:hidden")
                    if sessao.admin:
                        ui.badge("admin", color="amber-8").props("rounded")

                async def sair() -> None:
                    await sessao.sair()
                    ui.navigate.to("/login")

                ui.button("Sair", icon="logout", on_click=sair).props("flat color=white no-caps")
            else:
                ui.link("Entrar", "/login").classes("text-white")
                ui.link("Criar conta", "/cadastro").classes("text-white")

    if sessao.logado:
        with ui.left_drawer(bordered=True).classes("bg-white p-0").props("width=220") as gaveta:
            with ui.list().props("padding").classes("w-full"):
                for rota, rotulo, icone, so_admin in MENU:
                    if so_admin and not sessao.admin:
                        continue
                    selecionado = rota == ativa
                    with ui.item(on_click=lambda r=rota: ui.navigate.to(r)).props("clickable v-ripple").classes(
                        "rounded-r-full mr-2 " + ("bg-teal-50 text-teal-900 font-bold" if selecionado else "text-slate-700")
                    ):
                        with ui.item_section().props("avatar"):
                            ui.icon(icone, color="primary" if selecionado else "grey-7")
                        ui.item_section(rotulo)
            ui.separator().classes("my-2")
            ui.label("A chave privada nunca sai deste aparelho.").classes("text-xs text-slate-500 px-4")

    return ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4")


async def conectar(mensageiro: Mensageiro) -> None:
    """Toda tela logada garante o canal aberto (o indicador do cabeçalho mostra o estado).
    Chame antes da moldura: o que é aguardado depois dela chega ao navegador já com a página servida."""
    try:
        await mensageiro.conectar()
    except (ErroApi, httpx.HTTPError, OSError) as erro:
        ui.notify(f"Sem conexão com o servidor: {mensagem_erro(erro)}. Tentando de novo em segundo plano.", type="warning")


def _indicador_conexao(sessao: Sessao, mensageiro: Mensageiro) -> None:
    def estado() -> tuple[str, str]:
        if mensageiro.conectado:
            return "online", "positive"
        if mensageiro.reconectando:
            return "reconectando…", "warning"
        return "offline", "negative"

    texto, cor = estado()
    chip = ui.chip(texto, icon="circle").props(f"dense square color={cor} text-color=white").classes("text-xs")

    async def atualizar() -> None:
        if mensageiro.sessao_expirada and sessao.logado:
            ui.notify("O servidor encerrou a sessão (conta removida ou banco recriado). Entre de novo.", type="warning")
            await sessao.sair()
            ui.navigate.to("/login")
            return
        texto, cor = estado()
        if chip.text != texto:
            chip.text = texto
            chip.props(f"color={cor}")

    ui.timer(1.0, atualizar)


def avatar(username: str, imagem: str | None = None, tamanho: int = 10) -> None:
    """Iniciais coloridas por usuário (ou a imagem/emoji que ele escolheu)."""
    px = tamanho * 4
    if imagem and imagem.startswith(("http://", "https://")):
        ui.image(imagem).classes("rounded-full shrink-0").style(f"width:{px}px;height:{px}px")
        return
    cor = PALETA_AVATAR[int(hashlib.sha256(username.encode()).hexdigest(), 16) % len(PALETA_AVATAR)]
    texto = imagem or username[:2].upper()
    ui.label(texto).classes("rounded-full flex items-center justify-center text-white font-bold shrink-0 select-none").style(
        f"width:{px}px;height:{px}px;background:{cor};font-size:{max(px // 2.6, 10):.0f}px"
    )


def selo_modo(modo: str) -> None:
    ui.badge(NOME_MODO.get(modo, modo), color=COR_MODO.get(modo, "grey")).props("outline")


def secao(titulo: str, icone: str | None = None, descricao: str | None = None) -> ui.card:
    """Cartão com título; use `with secao(...):` para pôr o conteúdo."""
    cartao = ui.card().classes("w-full shadow-sm")
    with cartao:
        with ui.row().classes("items-center gap-2 no-wrap"):
            if icone:
                ui.icon(icone, color="primary").classes("text-xl")
            ui.label(titulo).classes("text-lg font-bold text-slate-800")
        if descricao:
            ui.label(descricao).classes("text-sm text-slate-600 -mt-2")
    return cartao


def titulo_pagina(titulo: str, subtitulo: str | None = None, icone: str | None = None) -> None:
    with ui.row().classes("items-center gap-3 no-wrap"):
        if icone:
            ui.icon(icone, color="primary").classes("text-3xl")
        with ui.column().classes("gap-0"):
            ui.label(titulo).classes("text-2xl font-bold text-slate-800")
            if subtitulo:
                ui.label(subtitulo).classes("text-sm text-slate-600")


def numero_seguranca(numero: str) -> None:
    """12 blocos de 5 dígitos, para comparar com o contato fora do app."""
    with ui.row().classes("gap-1 flex-wrap"):
        for bloco in numero.split():
            ui.label(bloco).classes("font-mono text-xs bg-slate-100 rounded px-1")


def mensagem_erro(erro: Exception) -> str:
    if isinstance(erro, ErroApi) and isinstance(erro.detalhe, list):  # erros de validação do Pydantic
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in erro.detalhe)
    if isinstance(erro, ErroApi):
        return str(erro.detalhe)
    return str(erro)


def encurtar(texto: str, tamanho: int = 48) -> str:
    return texto if len(texto) <= tamanho else texto[: tamanho - 1] + "…"


def hora(iso: str) -> str:
    """HH:MM de um ISO 8601 (o horário que o remetente declarou, em UTC)."""
    return iso[11:16] if len(iso) >= 16 else iso
