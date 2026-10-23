"""CRUD de clientes (RF12): listar com busca, editar, remover e reativar.

Criar é o cadastro (Passo 0). Cada um edita o próprio perfil; administradores editam qualquer um,
mudam o nó, promovem e removem. Remover revoga as chaves e derruba as sessões do cliente.
"""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import MODO, avatar, conectar, mensagem_erro, moldura, titulo_pagina
from frontend.sessao import Sessao
from shared.schemas import ClienteEdicaoIn, ClienteOut, ServidorOut


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/clientes")
    async def pagina():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        dados: dict = {"clientes": [], "nos": []}

        async def buscar() -> None:
            try:
                dados["clientes"] = await sessao.api.clientes()
                dados["nos"] = await sessao.api.servidores()
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")

        await buscar()
        with moldura(sessao, mensageiro, "/clientes"):
            titulo_pagina(
                "Clientes",
                "Usuários cadastrados. Criar conta é o Passo 0 (as chaves nascem no aparelho de cada um).",
                "group",
            )

            async def carregar() -> None:
                await buscar()
                lista.refresh()

            with ui.row().classes("w-full items-center gap-3"):
                busca = ui.input(placeholder="Buscar por usuário, nome ou nó").props("outlined dense clearable").classes(
                    "w-80"
                ).mark("cliente-busca")
                filtro = ui.toggle(
                    {"todos": "todos", "online": "online", **({"removidos": "removidos"} if sessao.admin else {})}, value="todos"
                ).props("dense no-caps")
                ui.space()
                ui.button("Atualizar", icon="refresh", on_click=carregar).props("flat")
                ui.button("Novo cliente", icon="person_add", on_click=lambda: ui.navigate.to("/cadastro")).props("outline").tooltip(
                    "O cadastro gera as chaves no aparelho de quem vai usá-las"
                )

            @ui.refreshable
            def lista() -> None:
                termo = (busca.value or "").strip().lower()
                visiveis = [
                    c for c in dados["clientes"]
                    if (not termo or termo in f"{c.username} {c.nome} {c.servidor or ''}".lower())
                    and (filtro.value != "online" or c.online)
                    and (c.ativo if filtro.value != "removidos" else not c.ativo)
                ]
                ui.label(f"{len(visiveis)} cliente(s)").classes("text-sm text-stone-500")
                with ui.column().classes("w-full gap-2"):
                    for cliente in visiveis:
                        _linha_cliente(sessao, cliente, dados["nos"], carregar)

            busca.on_value_change(lambda: lista.refresh())
            filtro.on_value_change(lambda: lista.refresh())
            lista()


def _linha_cliente(sessao: Sessao, cliente: ClienteOut, nos: list[ServidorOut], recarregar) -> None:
    eu = sessao.usuario
    proprio = cliente.id == eu.id
    with ui.card().classes("w-full shadow-sm " + ("opacity-60" if not cliente.ativo else "")):
        with ui.row().classes("items-center gap-3 w-full no-wrap max-md:flex-wrap"):
            with ui.element("div").classes("relative"):
                avatar(cliente.username, cliente.avatar, tamanho=11)
                cor = "bg-green-500" if cliente.online else "bg-stone-300"
                ui.element("span").classes(f"absolute bottom-0 right-0 w-3 h-3 rounded-full ring-2 ring-white {cor}")
            with ui.column().classes("gap-0 min-w-0 grow"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"@{cliente.username}").classes("font-bold")
                    ui.label(cliente.nome).classes("text-stone-600")
                    if proprio:
                        ui.badge("você", color="primary")
                    if cliente.is_admin:
                        ui.badge("admin").props("rounded color=primary")
                    if not cliente.ativo:
                        ui.badge("removido", color="negative")
                with ui.row().classes("items-center gap-2 text-xs text-stone-500"):
                    ui.icon("dns").classes("text-sm")
                    ui.label(cliente.servidor or "sem nó (relay central)")
                    ui.label("·")
                    ui.label(f"desde {cliente.criado_em.strftime('%d/%m/%Y %H:%M')}")
                    ui.label("·")
                    ui.label("online" if cliente.online else "offline")
            with ui.row().classes("gap-1 items-center"):
                if MODO not in cliente.modos_ativos:
                    ui.badge("sem chave ativa", color="grey-6").props("outline")
            with ui.row().classes("gap-1 no-wrap"):
                if cliente.ativo and (proprio or eu.is_admin):
                    ui.button(icon="edit", on_click=lambda: _dialogo_edicao(sessao, cliente, nos, recarregar)).props(
                        "flat round color=primary"
                    ).tooltip("Editar").mark(f"cliente-editar-{cliente.username}")
                if cliente.ativo and (proprio or eu.is_admin):
                    ui.button(icon="person_remove", on_click=lambda: _dialogo_remocao(sessao, cliente, recarregar)).props(
                        "flat round color=negative"
                    ).tooltip("Remover").mark(f"cliente-remover-{cliente.username}")
                if not cliente.ativo and eu.is_admin:

                    async def reativar() -> None:
                        try:
                            await sessao.api.editar_cliente(cliente.id, ClienteEdicaoIn(ativo=True))
                        except (ErroApi, httpx.HTTPError) as erro:
                            ui.notify(mensagem_erro(erro), type="negative")
                            return
                        ui.notify(f"@{cliente.username} reativado: ao entrar, publica uma nova chave", type="positive")
                        await recarregar()

                    ui.button("Reativar", icon="restore", on_click=reativar).props("flat no-caps").mark(
                        f"cliente-reativar-{cliente.username}"
                    )


def _dialogo_edicao(sessao: Sessao, cliente: ClienteOut, nos: list[ServidorOut], recarregar) -> None:
    admin = sessao.admin
    with ui.dialog() as dialogo, ui.card().classes("w-96"):
        ui.label(f"Editar @{cliente.username}").classes("text-lg font-bold")
        nome = ui.input("Nome", value=cliente.nome).classes("w-full").mark("cliente-nome")
        imagem = ui.input("Avatar (emoji, iniciais ou URL de imagem)", value=cliente.avatar or "").classes("w-full").mark("cliente-avatar")
        no = papel = None
        if admin:
            opcoes = {n.id: f"{n.nome}" + ("" if n.ativo else " (desligado)") for n in nos}
            no = ui.select(opcoes, value=cliente.server_id, label="Nó de origem").classes("w-full").mark("cliente-no")
            papel = ui.switch("Administrador", value=cliente.is_admin).mark("cliente-admin")
        else:
            ui.label("O nó e o papel são definidos por um administrador.").classes("text-xs text-stone-500")

        async def salvar() -> None:
            campos = {"nome": nome.value, "avatar": imagem.value or None}
            if no is not None and no.value != cliente.server_id:
                campos["server_id"] = no.value
            if papel is not None and papel.value != cliente.is_admin:
                campos["is_admin"] = papel.value
            try:
                await sessao.api.editar_cliente(cliente.id, ClienteEdicaoIn(**campos))
            except (ErroApi, httpx.HTTPError, ValueError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            if cliente.id == sessao.usuario.id:
                sessao.usuario = await sessao.api.eu()
            dialogo.close()
            ui.notify("Cliente atualizado", type="positive")
            await recarregar()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
            ui.button("Salvar", icon="save", on_click=salvar).mark("cliente-salvar")
    dialogo.open()


def _dialogo_remocao(sessao: Sessao, cliente: ClienteOut, recarregar) -> None:
    proprio = cliente.id == sessao.usuario.id
    with ui.dialog() as dialogo, ui.card().classes("w-96"):
        ui.label("Remover a sua conta" if proprio else f"Remover @{cliente.username}").classes("text-lg font-bold")
        ui.label(
            "As chaves públicas são revogadas (ninguém mais consegue cifrar para esta conta), os contatos são avisados "
            "e todas as sessões caem. As mensagens antigas continuam verificáveis por quem as recebeu."
        ).classes("text-sm")
        senha = ui.input("Confirme a sua senha", password=True).classes("w-full").mark("cliente-senha") if proprio else None

        async def confirmar() -> None:
            try:
                await sessao.api.remover_cliente(cliente.id, senha.value if senha is not None else None)
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            dialogo.close()
            if proprio:
                await sessao.sair()
                ui.navigate.to("/login")
                return
            ui.notify(f"@{cliente.username} removido; contatos avisados", type="warning")
            await recarregar()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
            ui.button("Remover", icon="person_remove", on_click=confirmar).props("color=negative").mark("cliente-confirmar-remocao")
    dialogo.open()
