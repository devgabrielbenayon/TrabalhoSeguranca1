"""Tela de chat: conversas 1:1 e em grupo, envio e recebimento em tempo real."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import ErroEnvio, ItemMensagem, Mensageiro
from frontend.pages.layout import cabecalho, mensagem_erro
from frontend.sessao import Sessao
from shared.crypto.blocos import MensagemGrandeDemais

MODOS = {"real": "real (RSA-OAEP 2048)", "didatico": "didático (RSA de livro)"}


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/chat")
    async def chat(conversa: int | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        cabecalho(sessao)
        try:
            await mensageiro.conectar()
        except (ErroApi, httpx.HTTPError, OSError) as erro:
            ui.notify(f"Sem conexão com o servidor: {mensagem_erro(erro)}", type="negative")

        estado = {"atual": conversa if conversa in mensageiro.conversas else next(iter(mensageiro.conversas), None)}

        def selecionar(conversation_id: int) -> None:
            estado["atual"] = conversation_id
            lista.refresh()
            mensagens.refresh()

        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-72 shrink-0"):
                ui.label("Nova conversa").classes("font-bold")
                participantes = ui.input("Usuários (vírgula)").classes("w-full").mark("chat-participantes")
                modo = ui.select(MODOS, value="real", label="Modo").classes("w-full")

                async def criar() -> None:
                    nomes = [u.strip() for u in (participantes.value or "").split(",") if u.strip()]
                    if not nomes:
                        return
                    try:
                        nova = await mensageiro.nova_conversa(nomes, modo.value)
                    except (ErroApi, httpx.HTTPError) as erro:
                        ui.notify(mensagem_erro(erro), type="negative")
                        return
                    participantes.value = ""
                    selecionar(nova.id)

                ui.button("Criar", on_click=criar).classes("w-full").mark("chat-criar")
                ui.separator()

                @ui.refreshable
                def lista() -> None:
                    if not mensageiro.conversas:
                        ui.label("Nenhuma conversa ainda").classes("text-gray-500 text-sm")
                    for c in mensageiro.conversas.values():
                        outros = ", ".join(p for p in c.participantes if p != sessao.usuario.username)
                        cor = "bg-teal-100" if c.id == estado["atual"] else ""
                        with ui.card().classes(f"w-full cursor-pointer {cor}").on("click", lambda c=c: selecionar(c.id)):
                            ui.label(outros).classes("font-bold")
                            with ui.row().classes("gap-1"):
                                ui.badge(c.tipo, color="gray")
                                ui.badge(c.modo, color="teal" if c.modo == "real" else "orange")

                lista()

            with ui.column().classes("grow"):

                @ui.refreshable
                def mensagens() -> None:
                    atual = mensageiro.conversas.get(estado["atual"])
                    if atual is None:
                        ui.label("Selecione ou crie uma conversa").classes("text-gray-500")
                        return
                    ui.label(", ".join(atual.participantes)).classes("text-lg font-bold")
                    ui.label(f"Modo {MODOS[atual.modo]} · um envelope cifrado e assinado por participante").classes(
                        "text-xs text-gray-600"
                    )
                    for item in atual.ordenadas():
                        _balao(item)

                mensagens()

                with ui.row().classes("w-full items-center no-wrap"):
                    texto = ui.input(placeholder="Mensagem").classes("grow").mark("chat-texto")

                    async def enviar() -> None:
                        if estado["atual"] is None or not (texto.value or "").strip():
                            return
                        conteudo, texto.value = texto.value, ""
                        try:
                            await mensageiro.enviar(estado["atual"], conteudo)
                        except (ErroEnvio, MensagemGrandeDemais) as erro:
                            ui.notify(str(erro), type="negative", multi_line=True)

                    texto.on("keydown.enter", enviar)
                    ui.button("Enviar", on_click=enviar).mark("chat-enviar")

        # o Mensageiro recebe em segundo plano; a tela redesenha quando a versão muda
        ultima = {"versao": mensageiro.versao}

        def atualizar() -> None:
            if mensageiro.versao != ultima["versao"]:
                ultima["versao"] = mensageiro.versao
                if estado["atual"] is None and mensageiro.conversas:
                    estado["atual"] = next(iter(mensageiro.conversas))
                lista.refresh()
                mensagens.refresh()

        ui.timer(0.3, atualizar)


def _balao(item: ItemMensagem) -> None:
    texto = item.texto if item.texto is not None else "[mensagem descartada]"
    with ui.chat_message(name=item.remetente, stamp=item.sent_at[11:16], sent=item.propria).classes("w-full"):
        ui.label(texto).classes("whitespace-pre-wrap" + (" text-red-700 italic" if item.texto is None else ""))
        ui.label(_status(item)).classes("text-xs " + ("text-red-700" if item.status in ("rejeitada", "erro") else "opacity-70"))


def _status(item: ItemMensagem) -> str:
    if item.status == "verificada":
        return f"✓ assinatura de {item.remetente} verificada ({item.key_id})"
    if item.status == "rejeitada":
        return f"✗ rejeitada: {item.erro}"
    if item.status == "erro":
        return f"✗ não enviada: {item.erro}"
    if item.status == "enviando":
        return "… cifrando e enviando"
    if item.status == "entregue":
        return "✓✓ entregue a todos"
    if item.aguardando:
        return f"✓ enviada · aguardando {', '.join(sorted(item.aguardando))}"
    return "✓ enviada"
