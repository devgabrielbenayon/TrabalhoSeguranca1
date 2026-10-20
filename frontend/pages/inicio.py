"""Dashboard: contadores do sistema, estado deste aparelho e o roteiro da demonstração."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import NOME_CHAVE, conectar, mensagem_erro, moldura, secao, selo_modo
from frontend.sessao import Sessao

# (título, o que fazer, rota, só administradores)
ROTEIRO = (
    ("Conversar", "Crie uma conversa 1:1 ou em grupo e troque mensagens: cada uma vira um envelope cifrado e assinado por participante.", "/chat", False),
    ("Ver a criptografia", "No Inspetor, siga a mensagem pelo raio-X: texto → blocos → mᵉ mod n → assinatura → rede → cᵈ mod n.", "/inspetor", False),
    ("Observar o servidor", "No Observador, veja o envelope passar pelos nós e o que o servidor e um interceptador enxergam.", "/observador", True),
    ("Derrubar um nó", "Em Servidores, desligue um nó do caminho: a rota é recalculada ou a mensagem espera (relógio).", "/servidores", False),
    ("Trocar ou excluir a chave", "Em Minhas chaves: os contatos recebem o alerta e o servidor passa a recusar a chave antiga.", "/chaves", False),
    ("Quebrar uma chave pequena", "No Laboratório, fatore o n de uma chave didática e veja por que 2048 bits.", "/laboratorio", False),
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
                    ui.badge("administrador", color="amber-8")
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
            with ui.row().classes("w-full gap-4 items-stretch"):
                with secao("Este aparelho", "smartphone").classes("grow basis-80"):
                    _linha("Conectado ao relay", "sim" if mensageiro.conectado else "não")
                    _linha("Nó de origem", eu.servidor if eu and eu.servidor else "relay central")
                    for modo in ("real", "didatico"):
                        privada = sessao.keystore.ativa(modo) if sessao.keystore else None
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f"{NOME_CHAVE[modo].capitalize()}:").classes("text-sm text-slate-600 w-28")
                            selo_modo(modo)
                            ui.label(privada.publica.key_id if privada else "sem chave privada ativa").classes("font-mono text-sm")
                    ui.button("Gerenciar chaves", icon="vpn_key", on_click=lambda: ui.navigate.to("/chaves")).props("flat")

                with secao("Roteiro da demonstração", "route").classes("grow basis-96"):
                    for numero, (titulo, texto, rota, so_admin) in enumerate(ROTEIRO, start=1):
                        if so_admin and not sessao.admin:
                            continue
                        with ui.row().classes("items-start gap-3 no-wrap w-full"):
                            ui.label(str(numero)).classes(
                                "rounded-full bg-teal-700 text-white w-6 h-6 flex items-center justify-center text-xs shrink-0 mt-1"
                            )
                            with ui.column().classes("gap-0 grow"):
                                ui.link(titulo, rota).classes("font-bold text-teal-800")
                                ui.label(texto).classes("text-sm text-slate-600")


def _contador(icone: str, titulo: str, valor, rodape: str, destaque: bool = False) -> None:
    with ui.card().classes("grow basis-40 shadow-sm " + ("bg-amber-50" if destaque else "")):
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.icon(icone, color="warning" if destaque else "primary").classes("text-2xl")
            ui.label(titulo).classes("text-sm text-slate-600")
        ui.label(str(valor)).classes("text-3xl font-bold text-slate-800")
        ui.label(rodape).classes("text-xs text-slate-500")


def _linha(rotulo: str, valor: str) -> None:
    with ui.row().classes("items-center gap-2"):
        ui.label(f"{rotulo}:").classes("text-sm text-slate-600 w-28")
        ui.label(valor).classes("text-sm font-medium")
