"""Tela de chat: conversas 1:1 e em grupo, envio e recebimento em tempo real."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import REMETENTE_SISTEMA, ConversaLocal, ErroEnvio, ItemMensagem, Mensageiro
from frontend.pages.layout import avatar, conectar, encurtar, hora, mensagem_erro, moldura, numero_seguranca, selo_modo
from frontend.sessao import Sessao
from shared.crypto.base import formatar_fingerprint
from shared.crypto.base import numero_seguranca as calcular_numero_seguranca
from shared.crypto.blocos import MAX_TEXTO_BYTES, MensagemGrandeDemais

MODOS = {"real": "real (RSA-OAEP 2048)", "didatico": "didático (RSA de livro)"}


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/chat")
    async def chat(conversa: int | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        # tudo que é aguardado vem antes da moldura: os timers dela fazem a página ser servida na hora
        await conectar(mensageiro)
        try:
            contatos = sorted(c.username for c in await sessao.api.clientes() if c.username != sessao.usuario.username)
        except (ErroApi, httpx.HTTPError):
            contatos = []
        conteudo = moldura(sessao, mensageiro, "/chat")

        estado = {"atual": conversa if conversa in mensageiro.conversas else _mais_recente(mensageiro)}

        def selecionar(conversation_id: int) -> None:
            estado["atual"] = conversation_id
            lista.refresh()
            mensagens.refresh()
            rolar_para_o_fim()

        with conteudo.classes("max-w-none"):
            with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
                # ---------------------------------------------------- coluna das conversas
                with ui.card().classes("w-80 shrink-0 shadow-sm gap-2"):
                    ui.label("Nova conversa").classes("font-bold text-slate-800")
                    participantes = ui.input(
                        "Usuários (vírgula)", autocomplete=contatos, placeholder="ex.: bob, carol"
                    ).classes("w-full").props("dense").mark("chat-participantes")
                    modo = ui.toggle({"real": "real", "didatico": "didático"}, value="real").props("dense no-caps spread").classes("w-full")

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

                    ui.button("Criar", icon="add_comment", on_click=criar).classes("w-full").props("unelevated").mark("chat-criar")
                    ui.separator()

                    @ui.refreshable
                    def lista() -> None:
                        if not mensageiro.conversas:
                            ui.label("Nenhuma conversa ainda").classes("text-slate-500 text-sm")
                        ordem = sorted(mensageiro.conversas.values(), key=_atividade, reverse=True)
                        with ui.column().classes("w-full gap-1"):
                            for c in ordem:
                                if c.id == estado["atual"]:
                                    c.nao_lidas = 0
                                _item_lista(sessao, c, c.id == estado["atual"], lambda c=c: selecionar(c.id))

                    lista()

                # ---------------------------------------------------- conversa aberta
                with ui.card().classes("grow shadow-sm gap-2 min-w-0"):

                    @ui.refreshable
                    def cabecalho_conversa() -> None:
                        atual = mensageiro.conversas.get(estado["atual"])
                        if atual is None:
                            return
                        outros = [p for p in atual.participantes if p != sessao.usuario.username]
                        with ui.row().classes("items-center gap-3 w-full no-wrap"):
                            if atual.tipo == "grupo":
                                ui.icon("groups", color="primary").classes("text-3xl")
                            else:
                                avatar(outros[0] if outros else "?")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(", ".join(atual.participantes)).classes("text-lg font-bold truncate")
                                with ui.row().classes("items-center gap-1"):
                                    ui.icon("lock", color="positive").classes("text-sm")
                                    ui.label(
                                        f"Modo {MODOS[atual.modo]} · um envelope cifrado e assinado por participante"
                                    ).classes("text-xs text-slate-600")
                            ui.button(icon="verified_user", on_click=lambda: _dialogo_seguranca(mensageiro, atual)).props(
                                "flat round color=primary"
                            ).tooltip("Números de segurança")
                        ui.separator()

                    cabecalho_conversa()

                    with ui.scroll_area().classes("w-full grow").style("height: calc(100vh - 290px); min-height: 280px") as area:

                        @ui.refreshable
                        def mensagens() -> None:
                            atual = mensageiro.conversas.get(estado["atual"])
                            if atual is None:
                                with ui.column().classes("w-full items-center py-16 text-slate-500"):
                                    ui.icon("forum").classes("text-6xl")
                                    ui.label("Selecione ou crie uma conversa")
                                return
                            if not atual.mensagens:
                                ui.label("Nenhuma mensagem. A primeira já sai cifrada e assinada.").classes(
                                    "w-full text-center text-sm text-slate-500 py-8"
                                )
                            for item in atual.ordenadas():
                                _balao(item)

                        mensagens()

                    def rolar_para_o_fim() -> None:
                        ui.timer(0.05, lambda: area.scroll_to(percent=1.0), once=True)

                    with ui.row().classes("w-full items-center no-wrap gap-2"):
                        texto = ui.input(placeholder="Mensagem").classes("grow").props("outlined dense").mark("chat-texto")
                        contador = ui.label(f"0/{MAX_TEXTO_BYTES} bytes").classes("text-xs text-slate-500 w-28 text-right")
                        texto.on_value_change(lambda e: _contar(contador, e.value))

                        async def enviar() -> None:
                            if estado["atual"] is None or not (texto.value or "").strip():
                                return
                            conteudo_texto, texto.value = texto.value, ""
                            try:
                                await mensageiro.enviar(estado["atual"], conteudo_texto)
                            except (ErroEnvio, MensagemGrandeDemais) as erro:
                                ui.notify(str(erro), type="negative", multi_line=True)
                                if not texto.value:
                                    texto.value = conteudo_texto  # não perde o que foi digitado
                            rolar_para_o_fim()

                        texto.on("keydown.enter", enviar)
                        ui.button(icon="send", on_click=enviar).props("round unelevated").mark("chat-enviar")

        # o Mensageiro recebe em segundo plano; a tela redesenha quando a versão muda
        ultima = {"versao": mensageiro.versao}

        def atualizar() -> None:
            if mensageiro.versao != ultima["versao"]:
                ultima["versao"] = mensageiro.versao
                if estado["atual"] not in mensageiro.conversas:
                    estado["atual"] = _mais_recente(mensageiro)
                lista.refresh()
                cabecalho_conversa.refresh()
                mensagens.refresh()
                rolar_para_o_fim()

        ui.timer(0.3, atualizar)
        rolar_para_o_fim()


def _atividade(conversa: ConversaLocal) -> str:
    ultima = conversa.ultima()
    return ultima.sent_at if ultima else ""


def _mais_recente(mensageiro: Mensageiro) -> int | None:
    if not mensageiro.conversas:
        return None
    return max(mensageiro.conversas.values(), key=lambda c: (_atividade(c), c.id)).id


def _item_lista(sessao: Sessao, conversa: ConversaLocal, selecionada: bool, ao_clicar) -> None:
    outros = [p for p in conversa.participantes if p != sessao.usuario.username]
    ultima = conversa.ultima()
    classes = "w-full rounded-lg p-2 cursor-pointer no-wrap items-center gap-2 "
    with ui.row().classes(classes + ("bg-teal-50 ring-1 ring-teal-200" if selecionada else "hover:bg-slate-50")).on("click", ao_clicar):
        if conversa.tipo == "grupo":
            ui.icon("groups", color="primary").classes("text-3xl shrink-0")
        else:
            avatar(outros[0] if outros else "?")
        with ui.column().classes("gap-0 grow min-w-0"):
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.label(", ".join(outros)).classes("font-bold truncate")
                ui.space()
                if ultima:
                    ui.label(hora(ultima.sent_at)).classes("text-xs text-slate-500")
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                previa = "sem mensagens" if ultima is None else (
                    ("você: " if ultima.propria else "") + (ultima.texto if ultima.texto is not None else "[descartada]")
                )
                ui.label(encurtar(previa, 34)).classes("text-xs text-slate-600 truncate grow")
                if conversa.nao_lidas:
                    ui.badge(str(conversa.nao_lidas), color="positive").props("rounded")
            with ui.row().classes("gap-1"):
                selo_modo(conversa.modo)
                if conversa.tipo == "grupo":
                    ui.badge("grupo", color="grey-7").props("outline")


def _contar(contador: ui.label, valor: str | None) -> None:
    tamanho = len((valor or "").encode("utf-8"))
    contador.text = f"{tamanho}/{MAX_TEXTO_BYTES} bytes"
    contador.classes(replace="text-xs w-28 text-right " + ("text-red-700 font-bold" if tamanho > MAX_TEXTO_BYTES else "text-slate-500"))


def _balao(item: ItemMensagem) -> None:
    if item.status == "aviso" or item.remetente == REMETENTE_SISTEMA:
        with ui.row().classes("w-full justify-center"):
            ui.label(item.texto).classes("text-center text-sm bg-amber-100 text-amber-900 rounded-lg px-3 py-2 max-w-xl")
        return
    descartada = item.texto is None
    cores = "bg-color=teal-1 text-color=grey-10" if item.propria else "bg-color=grey-2 text-color=grey-10"
    if descartada:
        cores = "bg-color=red-1 text-color=grey-10"
    with ui.chat_message(name=item.remetente, stamp=hora(item.sent_at), sent=item.propria).props(cores).classes("w-full"):
        ui.label(item.texto if not descartada else "[mensagem descartada]").classes(
            "whitespace-pre-wrap break-words" + (" text-red-700 italic" if descartada else "")
        )
        with ui.row().classes("items-center gap-1 no-wrap"):
            icone, cor = _icone_status(item)
            ui.icon(icone).classes(f"text-sm {cor}")
            ui.label(_status(item)).classes("text-xs " + ("text-red-700" if item.status in ("rejeitada", "erro") else "opacity-70"))
            if item.envelopes:
                ui.button(icon="biotech", on_click=lambda m=item.message_id: ui.navigate.to(f"/inspetor?mensagem={m}")).props(
                    "flat round dense size=xs"
                ).tooltip("Ver a criptografia desta mensagem no Inspetor")


def _icone_status(item: ItemMensagem) -> tuple[str, str]:
    if item.status in ("rejeitada", "erro"):
        return "error", "text-red-700"
    if item.status == "verificada":
        return "verified", "text-green-700"
    if item.status == "entregue":
        return "done_all", "text-sky-700"
    if item.sem_rota:
        return "schedule", "text-amber-700"
    if item.status == "enviando":
        return "hourglass_top", "opacity-70"
    return "done", "opacity-70"


def _status(item: ItemMensagem) -> str:
    if item.status == "verificada":
        return f"assinatura de {item.remetente} verificada ({item.key_id})"
    if item.status == "rejeitada":
        return f"rejeitada: {item.erro}"
    if item.status == "erro":
        return f"não enviada: {item.erro}"
    if item.status == "enviando":
        return "cifrando e enviando…"
    if item.status == "entregue":
        return "entregue a todos"
    if item.sem_rota:
        return f"na fila: sem caminho entre os nós até {', '.join(sorted(item.sem_rota))}"
    if item.aguardando:
        return f"enviada · aguardando {', '.join(sorted(item.aguardando))}"
    return "enviada"


def _dialogo_seguranca(mensageiro: Mensageiro, conversa: ConversaLocal) -> None:
    """Fingerprints conhecidos dos participantes: compare o número de segurança pessoalmente."""
    with ui.dialog() as dialogo, ui.card().classes("max-w-2xl"):
        ui.label("Números de segurança").classes("text-lg font-bold")
        ui.label(
            f"Chaves {"reais" if conversa.modo == "real" else "didáticas"} que este aparelho conhece. Se o número de alguém for diferente do que "
            "aparece no aparelho dele, o servidor pode ter trocado a chave (ataque MITM)."
        ).classes("text-sm text-slate-600")
        for participante in conversa.participantes:
            fingerprint = mensageiro.cache.conhecidas.get((participante, conversa.modo))
            if participante == mensageiro.eu and mensageiro.sessao.keystore:
                privada = mensageiro.sessao.keystore.ativa(conversa.modo)
                fingerprint = privada.publica.fingerprint if privada else None
            with ui.column().classes("gap-1 w-full border-b border-slate-100 py-2"):
                with ui.row().classes("items-center gap-2"):
                    avatar(participante, tamanho=7)
                    ui.label(f"@{participante}" + (" (você)" if participante == mensageiro.eu else "")).classes("font-bold")
                if fingerprint is None:
                    ui.label("ainda não buscada — envie uma mensagem primeiro").classes("text-xs text-slate-500")
                else:
                    ui.label(formatar_fingerprint(fingerprint)).classes("font-mono text-xs")
                    numero_seguranca(calcular_numero_seguranca(fingerprint))
        ui.button("Fechar", on_click=dialogo.close).props("flat")
    dialogo.open()
