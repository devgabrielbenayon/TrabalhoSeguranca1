"""Moldura comum às telas: cabeçalho, menu lateral, paleta e pequenos componentes visuais."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Callable

import httpx
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.sessao import Sessao

if TYPE_CHECKING:
    from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro

# paleta: menta, lima, pêssego, salmão e rosa; a "tinta" (ameixa escura) dá contraste a texto e botões
MENTA, LIMA, PESSEGO, SALMAO, ROSA = "#d2fae2", "#e6f8b1", "#f6d5ad", "#f6b794", "#e59da0"
TINTA = "#45324d"
CORES = {
    "primary": TINTA,
    "secondary": "#7b6680",
    "accent": ROSA,
    "positive": "#2f9e6a",
    "negative": "#c4505c",
    "warning": "#d9822b",
    "info": "#7b6680",
}
PALETA_AVATAR = (MENTA, LIMA, PESSEGO, SALMAO, ROSA, "#e9e1f0")
NOME_MODO = {"real": "real", "didatico": "didático"}
NOME_CHAVE = {"real": "chave real", "didatico": "chave didática"}
ICONE_MODO = {"real": "lock", "didatico": "school"}
TOM_MODO = {"real": "real", "didatico": "didatico"}
# tons semânticos (fundo, texto e cor do anel), definidos no CSS abaixo
TONS = {nome: f"tom-{nome}" for nome in ("ok", "real", "didatico", "alerta", "erro", "info", "neutro", "marca")}

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

CSS = f"""
:root {{--menta: {MENTA}; --lima: {LIMA}; --pessego: {PESSEGO}; --salmao: {SALMAO}; --rosa: {ROSA};
  --tinta: {TINTA}; --fundo: #fbf8f4; --borda: #eee5dd}}
body {{background: var(--fundo); color: #3b2f39}}
.q-card--bordered {{border-color: var(--borda)}}
.degrade {{background: linear-gradient(100deg, var(--menta) 0%, var(--lima) 27%, var(--pessego) 54%, var(--salmao) 78%, var(--rosa) 100%)}}

.tom-ok {{background: var(--menta); color: #1f5b3d; --tw-ring-color: #a7e8c2}}
.tom-real {{background: var(--lima); color: #4a5a10; --tw-ring-color: #cde68a}}
.tom-didatico {{background: var(--pessego); color: #7a4512; --tw-ring-color: #edbf8a}}
.tom-alerta {{background: #fcdcc9; color: #8a3f17; --tw-ring-color: var(--salmao)}}
.tom-erro {{background: #f8d6d7; color: #922f3a; --tw-ring-color: var(--rosa)}}
.tom-info {{background: #efe8f2; color: #4b3a57; --tw-ring-color: #dccfe4}}
.tom-neutro {{background: #f4efeb; color: #6a5d62; --tw-ring-color: #e6ddd6}}
.tom-marca {{background: linear-gradient(135deg, var(--menta), var(--lima)); color: var(--tinta); --tw-ring-color: #c7ecc0}}
.txt-tinta {{color: var(--tinta)}} .txt-ok {{color: #23704a}} .txt-alerta {{color: #9a4b17}}
.txt-erro {{color: #a8333f}} .txt-info {{color: #5b4868}}
.fundo-menta {{background: #ebfdf2}} .fundo-lima {{background: #f4fcd9}} .fundo-pessego {{background: #fdf1e2}}
.fundo-salmao {{background: #fdeadf}} .fundo-rosa {{background: #fbeaea}}

.clicavel {{transition: background .15s, box-shadow .15s}}
.clicavel:hover {{background: #f8f0e9}}
.selecionado, .selecionado:hover {{background: linear-gradient(90deg, rgba(246, 213, 173, .7), rgba(246, 183, 148, .25));
  box-shadow: inset 3px 0 0 var(--rosa)}}
.bolinha {{background: linear-gradient(135deg, var(--pessego), var(--salmao)); color: var(--tinta)}}
.quebra {{overflow-wrap: anywhere}}
.rotulo {{font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #8a7d83}}

.balao-meu {{background: var(--menta); box-shadow: 0 0 0 1px #b6edcf}}
.balao-outro {{background: #fff; box-shadow: 0 0 0 1px var(--borda)}}
.balao-erro {{background: #fbeaea; box-shadow: 0 0 0 1px #f0c3c5}}
.balao .acoes-balao {{opacity: .3; transition: opacity .15s}}
.balao:hover .acoes-balao {{opacity: 1}}

@keyframes surgir {{from {{opacity: 0; transform: translateY(8px)}} to {{opacity: 1; transform: none}}}}
.surgir {{animation: surgir .45s ease both}}
@keyframes fluxo {{to {{background-position: 16px 0}}}}
.fluxo {{height: 3px; border-radius: 3px; background: repeating-linear-gradient(90deg, #2f9e6a 0 8px, transparent 8px 16px);
  background-size: 16px 3px; animation: fluxo .7s linear infinite}}
.fluxo-fila {{height: 3px; border-radius: 3px; background: repeating-linear-gradient(90deg, #d9822b 0 6px, transparent 6px 10px)}}
.fluxo-parado {{height: 3px; border-radius: 3px; background: repeating-linear-gradient(90deg, var(--rosa) 0 4px, transparent 4px 8px)}}
@keyframes pulso {{0% {{box-shadow: 0 0 0 0 rgba(47, 158, 106, .45)}} 70%, 100% {{box-shadow: 0 0 0 14px rgba(47, 158, 106, 0)}}}}
.pulso {{animation: pulso 1.8s ease-out infinite}}
@media (prefers-reduced-motion: reduce) {{.surgir, .fluxo, .pulso {{animation: none}}}}

.q-timeline__title {{font-size: .95rem; font-weight: 600; margin-bottom: 2px}}
.q-timeline__subtitle {{font-size: .7rem}}
.q-timeline--dense .q-timeline__content {{padding-bottom: 12px}}
.nicegui-scroll-area .q-scrollarea__content {{width: 100%}}
.passo .q-item {{padding: 10px 12px; border-radius: 12px}}
.passo .q-item:hover {{background: #fbf6f1}}
"""


def tema() -> None:
    """Cores do Quasar e o CSS da paleta (toda página chama, logada ou não)."""
    ui.colors(**CORES)
    ui.add_css(CSS)


def moldura(sessao: Sessao, mensageiro: Mensageiro | None = None, ativa: str = "") -> ui.column:
    """Cabeçalho + menu (quando logado). Devolve a coluna onde a página põe o conteúdo."""
    tema()
    gaveta: ui.left_drawer | None = None

    with ui.header().classes("degrade items-center justify-between px-4 py-2 txt-tinta"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            if sessao.logado:
                ui.button(icon="menu", on_click=lambda: gaveta.toggle()).props("flat round dense color=primary")
            logotipo()
        with ui.row().classes("items-center gap-3 no-wrap"):
            if sessao.logado:
                if mensageiro is not None:
                    _indicador_conexao(sessao, mensageiro)
                with ui.row().classes("items-center gap-2 no-wrap"):
                    avatar(sessao.usuario.username, sessao.usuario.avatar, tamanho=8)
                    ui.label(f"@{sessao.usuario.username}").classes("font-semibold max-sm:hidden")
                    if sessao.admin:
                        ui.badge("admin").props("rounded color=primary")

                async def sair() -> None:
                    await sessao.sair()
                    ui.navigate.to("/login")

                ui.button("Sair", icon="logout", on_click=sair).props("flat color=primary no-caps")
            else:
                ui.link("Entrar", "/login").classes("txt-tinta font-medium")
                ui.link("Criar conta", "/cadastro").classes("txt-tinta font-medium")

    if sessao.logado:
        with ui.left_drawer(bordered=True).classes("bg-white p-0 flex flex-col").props("width=252") as gaveta:
            with ui.column().classes("w-full gap-0.5 py-3 grow"):
                for grupo, itens in MENU:
                    visiveis = [i for i in itens if not i[3] or sessao.admin]
                    if not visiveis:
                        continue
                    if grupo:
                        ui.label(grupo).classes("rotulo px-5 pt-4 pb-1")
                    for rota, rotulo, icone, _ in visiveis:
                        _item_menu(rota, rotulo, icone, rota == ativa)
            with ui.row().classes("items-start gap-2 no-wrap m-3 p-3 rounded-xl fundo-menta txt-tinta"):
                ui.icon("shield", color="positive").classes("text-lg")
                ui.label("A chave privada nunca sai deste aparelho.").classes("text-xs leading-snug")

    return ui.column().classes("w-full max-w-7xl mx-auto p-4 md:p-6 gap-5")


def logotipo(grande: bool = False) -> None:
    with ui.row().classes("items-center gap-2 no-wrap"):
        with ui.element("div").classes("rounded-xl bg-white/70 flex shadow-sm " + ("p-2" if grande else "p-1")):
            ui.icon("enhanced_encryption", color="primary").classes("text-3xl" if grande else "text-xl")
        ui.link("CriptoChat RSA", "/").classes(
            "font-bold txt-tinta no-underline tracking-wide " + ("text-2xl" if grande else "text-lg")
        )


def _item_menu(rota: str, rotulo: str, icone: str, selecionado: bool) -> None:
    """O item ocupa a largura toda do menu (alvo de clique maior que o texto)."""
    estado = "selecionado font-semibold txt-tinta" if selecionado else "text-stone-600"
    with ui.row().classes(f"clicavel self-stretch items-center gap-3 no-wrap mx-2 px-3 py-2.5 rounded-xl cursor-pointer {estado}").on(
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
    chip = ui.chip(texto, icon="circle").props(f"dense color=white text-color={cor}").classes("text-xs font-medium")

    async def atualizar() -> None:
        if mensageiro.sessao_expirada and sessao.logado:
            ui.notify("O servidor encerrou a sessão (conta removida ou banco recriado). Entre de novo.", type="warning")
            await sessao.sair()
            ui.navigate.to("/login")
            return
        texto, cor = estado()
        if chip.text != texto:
            chip.text = texto
            chip.props(f"text-color={cor}")

    ui.timer(1.0, atualizar)


# ---------------------------------------------------------------- componentes


def cartao(classes: str = "") -> ui.card:
    """Cartão claro com borda fina (sem sombra pesada)."""
    return ui.card().props("flat bordered").classes(f"rounded-2xl {classes}")


def icone_destaque(icone: str, tom: str = "marca", tamanho: str = "text-xl") -> None:
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
                ui.label(titulo).classes("text-base font-bold txt-tinta")
                if descricao:
                    ui.label(descricao).classes("text-xs text-stone-500")
    return caixa


def titulo_pagina(titulo: str, subtitulo: str | None = None, icone: str | None = None) -> None:
    with ui.row().classes("items-center gap-3 no-wrap"):
        if icone:
            icone_destaque(icone, tamanho="text-2xl")
        with ui.column().classes("gap-0"):
            ui.label(titulo).classes("text-2xl font-bold txt-tinta leading-tight")
            if subtitulo:
                ui.label(subtitulo).classes("text-sm text-stone-500")


def pilula(texto: str, tom: str = "neutro", icone: str | None = None) -> ui.row:
    """Etiqueta arredondada (status, modo, papel)."""
    with ui.row().classes(f"items-center gap-1 no-wrap rounded-full px-2 py-0.5 ring-1 {TONS[tom]}") as etiqueta:
        if icone:
            ui.icon(icone).classes("text-xs")
        ui.label(texto).classes("text-xs font-medium leading-tight whitespace-nowrap")
    return etiqueta


def selo_modo(modo: str) -> None:
    pilula(NOME_MODO.get(modo, modo), TOM_MODO.get(modo, "neutro"), ICONE_MODO.get(modo))


def avatar(username: str, imagem: str | None = None, tamanho: int = 10, online: bool | None = None) -> None:
    """Iniciais sobre um tom da paleta (ou a imagem/emoji que a pessoa escolheu); `online` põe o pontinho de status."""
    px = tamanho * 4
    with ui.element("div").classes("relative shrink-0").style(f"width:{px}px;height:{px}px"):
        if imagem and imagem.startswith(("http://", "https://")):
            ui.image(imagem).classes("rounded-full w-full h-full")
        else:
            cor = PALETA_AVATAR[int(hashlib.sha256(username.encode()).hexdigest(), 16) % len(PALETA_AVATAR)]
            ui.label(imagem or username[:2].upper()).classes(
                "rounded-full w-full h-full flex items-center justify-center font-bold select-none txt-tinta"
            ).style(f"background:{cor};font-size:{max(px // 2.6, 10):.0f}px;box-shadow:0 0 0 1px rgba(69,50,77,.08)")
        if online is not None:
            ui.element("span").classes("absolute bottom-0 right-0 rounded-full ring-2 ring-white").style(
                f"width:{max(px // 4, 8)}px;height:{max(px // 4, 8)}px;background:{'#2f9e6a' if online else '#cfc4c9'}"
            )


def vazio(icone: str, texto: str) -> None:
    """Estado vazio: ícone grande e uma frase."""
    with ui.column().classes("w-full items-center gap-2 py-16 text-stone-400"):
        ui.icon(icone).classes("text-6xl")
        ui.label(texto).classes("text-sm text-stone-500 text-center")


def numero_seguranca(numero: str) -> None:
    """12 blocos de 5 dígitos, para comparar com o contato fora do app."""
    with ui.row().classes("gap-1 flex-wrap"):
        for bloco in numero.split():
            ui.label(bloco).classes("font-mono text-xs bg-stone-100 rounded px-1")


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
    estado = "selecionado" if selecionado else ""
    with ui.row().classes(f"clicavel w-full rounded-xl p-2 gap-2 no-wrap cursor-pointer items-start {estado}").on("click", ao_clicar):
        ui.icon("north_east" if item.propria else "south_west", color="primary" if item.propria else "accent").classes(
            "text-lg mt-0.5"
        )
        with ui.column().classes("gap-0 min-w-0 grow"):
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.label(("você" if item.propria else f"@{item.remetente}") + f" → {destino}").classes(
                    "text-sm font-medium truncate grow txt-tinta"
                )
                ui.label(hora(item.sent_at)).classes("text-xs text-stone-400 shrink-0")
            ui.label(encurtar(item.texto if item.texto is not None else "[não foi possível ler]", 40)).classes(
                "text-xs text-stone-500 truncate"
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
