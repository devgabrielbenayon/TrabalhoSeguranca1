"""Moldura comum às telas: cabeçalho, menu lateral e pequenos componentes visuais."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Callable

import httpx
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.sessao import Sessao

if TYPE_CHECKING:
    from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro

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
NOME_MODO = {"real": "real", "didatico": "didático"}
NOME_CHAVE = {"real": "chave real", "didatico": "chave didática"}
ICONE_MODO = {"real": "lock", "didatico": "school"}
TOM_MODO = {"real": "teal", "didatico": "ambar"}
TONS = {
    "teal": "bg-teal-50 text-teal-800 ring-teal-200",
    "verde": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "ambar": "bg-amber-50 text-amber-800 ring-amber-200",
    "vermelho": "bg-red-50 text-red-700 ring-red-200",
    "azul": "bg-sky-50 text-sky-800 ring-sky-200",
    "cinza": "bg-slate-100 text-slate-600 ring-slate-200",
}

# (grupo, ((rota, rótulo, ícone, só administradores), ...))
MENU = (
    ("", (
        ("/", "Início", "space_dashboard", False),
        ("/chat", "Chat", "forum", False),
    )),
    ("Por dentro da criptografia", (
        ("/inspetor", "Inspetor", "biotech", False),
        ("/caminho", "Caminho da mensagem", "route", False),
        ("/chaves", "Minhas chaves", "vpn_key", False),
    )),
    ("Rede", (
        ("/observador", "Observador", "hub", True),
        ("/servidores", "Servidores", "dns", False),
        ("/clientes", "Clientes", "group", False),
    )),
)

CSS = """
@keyframes surgir {from {opacity: 0; transform: translateY(8px)} to {opacity: 1; transform: none}}
.surgir {animation: surgir .45s ease both}
.q-timeline__title {font-size: .95rem; font-weight: 600; margin-bottom: 2px}
.q-timeline__subtitle {font-size: .7rem}
.q-timeline--dense .q-timeline__content {padding-bottom: 12px}
.nicegui-scroll-area .q-scrollarea__content {width: 100%}
.rotulo {font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #64748b}
.balao .acoes-balao {opacity: .3; transition: opacity .15s}
.balao:hover .acoes-balao {opacity: 1}
.passo .q-item {padding: 10px 12px; border-radius: 12px}
.passo .q-item:hover {background: #f8fafc}
"""


def moldura(sessao: Sessao, mensageiro: Mensageiro | None = None, ativa: str = "") -> ui.column:
    """Cabeçalho + menu (quando logado). Devolve a coluna onde a página põe o conteúdo."""
    ui.colors(**CORES)
    ui.query("body").classes("bg-slate-50")
    # entrada escalonada (animação feita no navegador): style="animation-delay: …" em cada elemento .surgir
    ui.add_css(CSS)
    gaveta: ui.left_drawer | None = None

    with ui.header().classes("items-center justify-between px-4 py-2").style(
        "background: linear-gradient(90deg, #134e4a 0%, #0f766e 100%)"
    ):
        with ui.row().classes("items-center gap-2 no-wrap"):
            if sessao.logado:
                ui.button(icon="menu", on_click=lambda: gaveta.toggle()).props("flat round dense color=white")
            with ui.element("div").classes("rounded-lg bg-white/15 p-1 flex"):
                ui.icon("enhanced_encryption", color="white").classes("text-xl")
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
        with ui.left_drawer(bordered=True).classes("bg-white p-0 flex flex-col").props("width=248") as gaveta:
            with ui.column().classes("w-full gap-0 py-3 grow"):
                for grupo, itens in MENU:
                    visiveis = [i for i in itens if not i[3] or sessao.admin]
                    if not visiveis:
                        continue
                    if grupo:
                        ui.label(grupo).classes("rotulo px-5 pt-4 pb-1")
                    for rota, rotulo, icone, _ in visiveis:
                        _item_menu(rota, rotulo, icone, rota == ativa)
            with ui.row().classes("items-start gap-2 no-wrap m-3 p-3 rounded-xl bg-teal-50 text-teal-900"):
                ui.icon("shield", color="primary").classes("text-lg")
                ui.label("A chave privada nunca sai deste aparelho.").classes("text-xs leading-snug")

    return ui.column().classes("w-full max-w-7xl mx-auto p-4 md:p-6 gap-5")


def _item_menu(rota: str, rotulo: str, icone: str, selecionado: bool) -> None:
    cores = "bg-teal-50 text-teal-900 font-semibold" if selecionado else "text-slate-700 hover:bg-slate-50"
    with ui.row().classes(f"items-center gap-3 no-wrap mx-3 px-3 py-2 rounded-xl cursor-pointer {cores}").on(
        "click", lambda: ui.navigate.to(rota)
    ):
        ui.icon(icone, color="primary" if selecionado else "grey-7").classes("text-xl")
        ui.label(rotulo).classes("text-sm")


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
    chip = ui.chip(texto, icon="circle").props(f"dense color={cor} text-color=white").classes("text-xs")

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


# ---------------------------------------------------------------- componentes


def cartao(classes: str = "") -> ui.card:
    """Cartão claro com borda fina (sem sombra pesada)."""
    return ui.card().props("flat bordered").classes(f"rounded-2xl {classes}")


def icone_destaque(icone: str, tom: str = "teal", tamanho: str = "text-xl") -> None:
    """Ícone dentro de um quadradinho colorido (cabeçalhos de seção e de página)."""
    with ui.element("div").classes(f"rounded-xl p-2 flex shrink-0 ring-1 {TONS[tom]}"):
        ui.icon(icone).classes(tamanho)


def secao(titulo: str, icone: str | None = None, descricao: str | None = None) -> ui.card:
    """Cartão com título; use `with secao(...):` para pôr o conteúdo."""
    caixa = cartao("w-full")
    with caixa:
        with ui.row().classes("items-center gap-3 no-wrap"):
            if icone:
                icone_destaque(icone)
            with ui.column().classes("gap-0"):
                ui.label(titulo).classes("text-base font-bold text-slate-800")
                if descricao:
                    ui.label(descricao).classes("text-xs text-slate-500")
    return caixa


def titulo_pagina(titulo: str, subtitulo: str | None = None, icone: str | None = None) -> None:
    with ui.row().classes("items-center gap-3 no-wrap"):
        if icone:
            icone_destaque(icone, tamanho="text-2xl")
        with ui.column().classes("gap-0"):
            ui.label(titulo).classes("text-2xl font-bold text-slate-800 leading-tight")
            if subtitulo:
                ui.label(subtitulo).classes("text-sm text-slate-500")


def pilula(texto: str, tom: str = "cinza", icone: str | None = None) -> ui.row:
    """Etiqueta arredondada (status, modo, papel)."""
    with ui.row().classes(f"items-center gap-1 no-wrap rounded-full px-2 py-0.5 ring-1 {TONS[tom]}") as etiqueta:
        if icone:
            ui.icon(icone).classes("text-xs")
        ui.label(texto).classes("text-xs font-medium leading-tight whitespace-nowrap")
    return etiqueta


def selo_modo(modo: str) -> None:
    pilula(NOME_MODO.get(modo, modo), TOM_MODO.get(modo, "cinza"), ICONE_MODO.get(modo))


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


def vazio(icone: str, texto: str) -> None:
    """Estado vazio: ícone grande e uma frase."""
    with ui.column().classes("w-full items-center gap-2 py-16 text-slate-400"):
        ui.icon(icone).classes("text-6xl")
        ui.label(texto).classes("text-sm text-slate-500 text-center")


def numero_seguranca(numero: str) -> None:
    """12 blocos de 5 dígitos, para comparar com o contato fora do app."""
    with ui.row().classes("gap-1 flex-wrap"):
        for bloco in numero.split():
            ui.label(bloco).classes("font-mono text-xs bg-slate-100 rounded px-1")


# ---------------------------------------------------------------- lista de mensagens (Inspetor e Caminho)


def mensagens_com_envelope(mensageiro: Mensageiro) -> list[tuple[ConversaLocal, ItemMensagem]]:
    """Da mais nova para a mais antiga; só as que têm envelope (avisos locais ficam de fora)."""
    return sorted(
        ((c, i) for c in mensageiro.conversas.values() for i in c.mensagens.values() if i.envelopes),
        key=lambda ci: ci[1].sent_at,
        reverse=True,
    )


def item_mensagem(conversa: ConversaLocal, item: ItemMensagem, selecionado: bool, ao_clicar: Callable[[], None]) -> None:
    destino = ", ".join(f"@{p}" for p in conversa.participantes if p != item.remetente)
    cores = "bg-teal-50 ring-1 ring-teal-200" if selecionado else "hover:bg-slate-50"
    with ui.row().classes(f"w-full rounded-xl p-2 gap-2 no-wrap cursor-pointer items-start {cores}").on("click", ao_clicar):
        ui.icon("north_east" if item.propria else "south_west", color="primary" if item.propria else "info").classes(
            "text-lg mt-0.5"
        )
        with ui.column().classes("gap-0 min-w-0 grow"):
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.label(("você" if item.propria else f"@{item.remetente}") + f" → {destino}").classes(
                    "text-sm font-medium truncate grow"
                )
                ui.label(hora(item.sent_at)).classes("text-xs text-slate-400 shrink-0")
            ui.label(encurtar(item.texto if item.texto is not None else "[não foi possível ler]", 40)).classes(
                "text-xs text-slate-500 truncate"
            )
            with ui.row().classes("pt-1"):
                selo_modo(conversa.modo)


# ---------------------------------------------------------------- texto


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
