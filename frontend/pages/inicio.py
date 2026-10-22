"""Dashboard: contadores do sistema, estado deste aparelho e o roteiro da demonstração."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import NOME_CHAVE, cartao, conectar, icone_destaque, mensagem_erro, moldura, pilula, secao, selo_modo
from frontend.sessao import Sessao

# (título, o que fazer, rota, ícone, só administradores)
ROTEIRO = (
    ("Conversar", "Crie uma conversa e troque mensagens: cada uma sai cifrada e assinada.", "/chat", "forum", False),
    ("Ver a criptografia", "No Inspetor, siga a mensagem passo a passo: texto → mᵉ mod n → cᵈ mod n → texto.", "/inspetor", "biotech", False),
    ("Seguir o caminho", "Veja o envelope cifrado atravessar os nós até o destinatário.", "/caminho", "route", False),
    ("Observar o servidor", "O que o servidor e um espião na rede enxergam de todo o tráfego.", "/observador", "hub", True),
    ("Derrubar um nó", "Desligue um nó do caminho: a rota é recalculada ou a mensagem espera na fila.", "/servidores", "dns", False),
    ("Trocar ou excluir a chave", "Os contatos são avisados e o servidor passa a recusar a chave antiga.", "/chaves", "vpn_key", False),
)


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/")
    async def inicio():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        try:
            estatisticas = await sessao.api.estatisticas()
            clientes = await sessao.api.clientes()
        except (ErroApi, httpx.HTTPError) as erro:
            estatisticas = clientes = None
            ui.notify(mensagem_erro(erro), type="negative")
        with moldura(sessao, mensageiro, "/"):
            with ui.row().classes("items-center gap-3"):
                ui.label(f"Olá, {sessao.usuario.nome}").classes("text-2xl font-bold text-slate-800")
                if sessao.admin:
                    pilula("administrador", "ambar", "admin_panel_settings")
            if estatisticas is None:
                return

            with ui.row().classes("w-full gap-4"):
                _contador("group", "Clientes", estatisticas.clientes, f"{estatisticas.online} online agora")
                _contador("dns", "Nós ligados", f"{estatisticas.servidores_ativos}/{estatisticas.servidores}", "nós de retransmissão")
                _contador("forum", "Conversas", estatisticas.conversas, f"{estatisticas.minhas_conversas} com você")
                _contador("mail", "Mensagens", estatisticas.mensagens, f"{estatisticas.minhas_mensagens} enviadas por você")
                _contador(
                    "schedule", "Na fila", estatisticas.envelopes_pendentes, "envelopes aguardando entrega",
                    destaque=estatisticas.envelopes_pendentes > 0,
                )

            eu = next((c for c in clientes if c.id == sessao.usuario.id), None)
            with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
                with secao("Roteiro da demonstração", "route", "Um caminho pelas telas, na ordem da apresentação.").style("flex: 2 1 28rem"):
                    passos = [p for p in ROTEIRO if not p[4] or sessao.admin]
                    with ui.element("div").classes("w-full grid gap-3 grid-cols-1 md:grid-cols-2"):
                        for numero, (titulo, texto, rota, icone, _) in enumerate(passos, start=1):
                            _passo_roteiro(numero, titulo, texto, rota, icone)

                with secao("Este aparelho", "smartphone").style("flex: 1 1 18rem"):
                    _linha("Conexão", "conectado ao relay" if mensageiro.conectado else "desconectado")
                    _linha("Nó de origem", eu.servidor if eu and eu.servidor else "relay central")
                    ui.label("Chaves privadas em uso").classes("rotulo pt-2")
                    for modo in ("real", "didatico"):
                        privada = sessao.keystore.ativa(modo) if sessao.keystore else None
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            selo_modo(modo)
                            ui.label(privada.publica.key_id if privada else f"sem {NOME_CHAVE[modo]}").classes(
                                "font-mono text-sm " + ("text-slate-800" if privada else "text-red-700")
                            )
                    ui.button("Ver minhas chaves", icon="vpn_key", on_click=lambda: ui.navigate.to("/chaves")).props(
                        "flat no-caps color=primary"
                    ).classes("mt-auto")


def _contador(icone: str, titulo: str, valor, rodape: str, destaque: bool = False) -> None:
    with cartao("grow basis-40 gap-1 " + ("bg-amber-50" if destaque else "")):
        with ui.row().classes("items-center gap-2 no-wrap"):
            icone_destaque(icone, "ambar" if destaque else "teal", "text-lg")
            ui.label(titulo).classes("text-sm text-slate-600")
        ui.label(str(valor)).classes("text-3xl font-bold text-slate-800 pt-1")
        ui.label(rodape).classes("text-xs text-slate-500")


def _passo_roteiro(numero: int, titulo: str, texto: str, rota: str, icone: str) -> None:
    with ui.row().classes(
        "items-start gap-3 no-wrap rounded-xl p-3 ring-1 ring-slate-200 hover:ring-teal-400 hover:bg-teal-50/40 cursor-pointer"
    ).on("click", lambda: ui.navigate.to(rota)):
        ui.label(str(numero)).classes(
            "rounded-full bg-teal-700 text-white w-7 h-7 flex items-center justify-center text-sm font-bold shrink-0"
        )
        with ui.column().classes("gap-0 grow"):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.icon(icone, color="primary").classes("text-base")
                ui.label(titulo).classes("font-bold text-teal-900")
            ui.label(texto).classes("text-sm text-slate-600")


def _linha(rotulo: str, valor: str) -> None:
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label(rotulo).classes("text-sm text-slate-500 w-28 shrink-0")
        ui.label(valor).classes("text-sm font-medium")
