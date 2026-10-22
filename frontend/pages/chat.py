"""Tela de chat: conversas 1:1 e em grupo, envio e recebimento em tempo real."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import REMETENTE_SISTEMA, ConversaLocal, ErroEnvio, ItemMensagem, Mensageiro
from frontend.pages.layout import (
    ICONE_MODO,
    avatar,
    cartao,
    conectar,
    encurtar,
    hora,
    mensagem_erro,
    moldura,
    numero_seguranca,
    vazio,
)
from frontend.sessao import Sessao
from shared.crypto.base import formatar_fingerprint
from shared.crypto.base import numero_seguranca as calcular_numero_seguranca
from shared.crypto.blocos import MAX_TEXTO_CARACTERES, MensagemGrandeDemais

MODOS = {"real": "RSA real (2048 bits)", "didatico": "RSA didático (números pequenos)"}
# (título, explicação) de cada modo no diálogo de nova conversa
OPCOES_MODO = {
    "real": ("Real", "RSA de 2048 bits: o que se usa de verdade."),
    "didatico": ("Didático", "Números pequenos, para ver a matemática no Inspetor."),
}


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
            cabecalho_conversa.refresh()
            mensagens.refresh()
            rolar_para_o_fim()

        nova = _dialogo_nova_conversa(mensageiro, contatos, selecionar)

        with conteudo.classes("max-w-none"):
            with ui.row().classes("w-full no-wrap gap-4 items-stretch").style("height: calc(100vh - 112px); min-height: 460px"):
                # ---------------------------------------------------- coluna das conversas
                with cartao("w-80 shrink-0 gap-2 p-3"):
                    with ui.row().classes("w-full items-center no-wrap px-1"):
                        ui.label("Conversas").classes("text-lg font-bold text-slate-800 grow")
                        ui.button(icon="add", on_click=nova.open).props("round unelevated color=primary size=sm").tooltip(
                            "Nova conversa"
                        ).mark("chat-nova")
                    with ui.scroll_area().classes("w-full grow min-h-0"):

                        @ui.refreshable
                        def lista() -> None:
                            if not mensageiro.conversas:
                                ui.label("Nenhuma conversa ainda. Toque em + para começar.").classes(
                                    "text-slate-500 text-sm px-1"
                                )
                            ordem = sorted(mensageiro.conversas.values(), key=_atividade, reverse=True)
                            with ui.column().classes("w-full gap-1"):
                                for c in ordem:
                                    if c.id == estado["atual"]:
                                        c.nao_lidas = 0
                                    _item_lista(sessao, c, c.id == estado["atual"], lambda c=c: selecionar(c.id))

                        lista()

                # ---------------------------------------------------- conversa aberta
                with cartao("grow min-w-0 p-0 gap-0 overflow-hidden"):

                    @ui.refreshable
                    def cabecalho_conversa() -> None:
                        atual = mensageiro.conversas.get(estado["atual"])
                        if atual is None:
                            return
                        outros = [p for p in atual.participantes if p != sessao.usuario.username]
                        with ui.row().classes("items-center gap-3 w-full no-wrap px-4 py-3 border-b border-slate-200 bg-white"):
                            if atual.tipo == "grupo":
                                _icone_grupo()
                            else:
                                avatar(outros[0] if outros else "?")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(", ".join(f"@{p}" for p in outros)).classes("text-base font-bold truncate")
                                with ui.row().classes("items-center gap-1 no-wrap"):
                                    ui.icon("lock", color="positive").classes("text-sm")
                                    ui.label(f"Criptografia ponta a ponta · {MODOS[atual.modo]}").classes("text-xs text-slate-500")
                            ui.button(icon="verified_user", on_click=lambda: _dialogo_seguranca(mensageiro, atual)).props(
                                "flat round color=primary"
                            ).tooltip("Números de segurança")

                    cabecalho_conversa()

                    with ui.scroll_area().classes("w-full grow min-h-0 bg-slate-50") as area:

                        @ui.refreshable
                        def mensagens() -> None:
                            atual = mensageiro.conversas.get(estado["atual"])
                            if atual is None:
                                vazio("forum", "Selecione uma conversa ou crie uma nova")
                                with ui.row().classes("w-full justify-center"):
                                    ui.button("Nova conversa", icon="add", on_click=nova.open).props("unelevated no-caps")
                                return
                            if not atual.mensagens:
                                vazio("lock", "Nenhuma mensagem ainda. A primeira já sai cifrada e assinada.")
                            with ui.column().classes("w-full gap-2 px-2 py-3"):
                                for item in atual.ordenadas():
                                    _balao(item, atual.tipo == "grupo")

                        mensagens()

                    def rolar_para_o_fim() -> None:
                        ui.timer(0.05, lambda: area.scroll_to(percent=1.0), once=True)

                    with ui.row().classes("w-full items-center no-wrap gap-2 px-3 py-3 border-t border-slate-200 bg-white"):
                        texto = ui.input(placeholder="Escreva uma mensagem").classes("grow").props(
                            f"outlined dense rounded maxlength={MAX_TEXTO_CARACTERES}"
                        ).mark("chat-texto")
                        contador = ui.label().classes("text-xs text-slate-400 w-32 text-right shrink-0")
                        _contar(contador, "")
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
                        ui.button(icon="send", on_click=enviar).props("round unelevated color=primary").mark("chat-enviar")

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


def _icone_grupo() -> None:
    with ui.element("div").classes("rounded-full bg-teal-100 text-teal-800 flex items-center justify-center shrink-0").style(
        "width:40px;height:40px"
    ):
        ui.icon("groups").classes("text-2xl")


def _dialogo_nova_conversa(mensageiro: Mensageiro, contatos: list[str], ao_criar) -> ui.dialog:
    escolha = {"modo": "real"}
    opcoes: dict[str, ui.column] = {}

    def classes_opcao(marcada: bool) -> str:
        cores = "ring-2 ring-teal-600 bg-teal-50" if marcada else "ring-1 ring-slate-200 hover:bg-slate-50"
        return f"flex flex-col grow basis-0 gap-0.5 p-3 rounded-xl cursor-pointer {cores}"

    def escolher(modo: str) -> None:
        escolha["modo"] = modo
        for chave, opcao in opcoes.items():
            opcao.classes(replace=classes_opcao(chave == modo))

    with ui.dialog() as dialogo, cartao("w-[440px] max-w-full gap-3 p-5"):
        ui.label("Nova conversa").classes("text-lg font-bold text-slate-800")
        participantes = ui.input(
            "Com quem?", autocomplete=contatos, placeholder="ex.: bob, carol"
        ).classes("w-full").props("outlined dense").mark("chat-participantes")
        ui.label("Separe os nomes por vírgula para criar um grupo.").classes("text-xs text-slate-500 -mt-2")
        ui.label("Criptografia").classes("rotulo mt-1")
        with ui.row().classes("w-full gap-2 no-wrap"):
            for modo, (titulo, explicacao) in OPCOES_MODO.items():
                with ui.element("div").classes(classes_opcao(modo == "real")).on(
                    "click", lambda m=modo: escolher(m)
                ).mark(f"chat-modo-{modo}") as opcao:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon(ICONE_MODO[modo], color="primary" if modo == "real" else "warning")
                        ui.label(titulo).classes("font-bold text-sm")
                    ui.label(explicacao).classes("text-xs text-slate-600")
                opcoes[modo] = opcao

        async def criar() -> None:
            nomes = [u.strip() for u in (participantes.value or "").split(",") if u.strip()]
            if not nomes:
                return
            try:
                nova = await mensageiro.nova_conversa(nomes, escolha["modo"])
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            participantes.value = ""
            dialogo.close()
            ao_criar(nova.id)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat no-caps")
            ui.button("Criar conversa", icon="add_comment", on_click=criar).props("unelevated no-caps").mark("chat-criar")
    return dialogo


def _item_lista(sessao: Sessao, conversa: ConversaLocal, selecionada: bool, ao_clicar) -> None:
    outros = [p for p in conversa.participantes if p != sessao.usuario.username]
    ultima = conversa.ultima()
    cores = "bg-teal-50" if selecionada else "hover:bg-slate-50"
    with ui.row().classes(f"w-full rounded-xl p-2 cursor-pointer no-wrap items-center gap-3 {cores}").on("click", ao_clicar):
        if conversa.tipo == "grupo":
            _icone_grupo()
        else:
            avatar(outros[0] if outros else "?")
        with ui.column().classes("gap-0 grow min-w-0"):
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.label(", ".join(outros)).classes("font-semibold text-slate-800 truncate grow")
                if ultima:
                    ui.label(hora(ultima.sent_at)).classes("text-xs text-slate-400 shrink-0")
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                ui.icon(ICONE_MODO[conversa.modo], color="primary" if conversa.modo == "real" else "warning").classes(
                    "text-xs shrink-0"
                ).tooltip(f"modo {MODOS[conversa.modo]}")
                previa = "sem mensagens" if ultima is None else (
                    ("você: " if ultima.propria else "") + (ultima.texto if ultima.texto is not None else "[não foi possível ler]")
                )
                ui.label(encurtar(previa, 34)).classes("text-xs text-slate-500 truncate grow")
                if conversa.nao_lidas:
                    ui.badge(str(conversa.nao_lidas), color="positive").props("rounded")


def _contar(contador: ui.label, valor: str | None) -> None:
    tamanho = len(valor or "")
    contador.text = f"{tamanho}/{MAX_TEXTO_CARACTERES} caracteres"
    cor = "text-red-700 font-bold" if tamanho >= MAX_TEXTO_CARACTERES else "text-slate-400"
    contador.classes(replace=f"text-xs w-32 text-right shrink-0 {cor}")


def _balao(item: ItemMensagem, grupo: bool) -> None:
    if item.status == "aviso" or item.remetente == REMETENTE_SISTEMA:
        with ui.row().classes("w-full justify-center"):
            with ui.row().classes("items-start gap-2 no-wrap max-w-xl rounded-xl px-3 py-2 bg-amber-50 ring-1 ring-amber-200"):
                ui.icon("key", color="warning").classes("text-base mt-0.5")
                ui.label(item.texto).classes("text-xs text-amber-900")
        return
    descartada = item.texto is None
    if descartada:
        cores = "bg-red-50 ring-1 ring-red-200"
    elif item.propria:
        cores = "bg-teal-100/70 ring-1 ring-teal-200"
    else:
        cores = "bg-white ring-1 ring-slate-200"
    canto = "rounded-br-md" if item.propria else "rounded-bl-md"
    with ui.column().classes("w-full gap-0.5 balao " + ("items-end" if item.propria else "items-start")):
        with ui.column().classes(f"gap-0.5 rounded-2xl {canto} px-3 py-2 {cores}").style("max-width: min(70%, 640px)"):
            if grupo and not item.propria:
                ui.label(f"@{item.remetente}").classes("text-xs font-bold text-teal-800")
            ui.label(item.texto if not descartada else "[mensagem descartada]").classes(
                "text-sm whitespace-pre-wrap break-words " + ("text-red-700 italic" if descartada else "text-slate-900")
            )
            with ui.row().classes("items-center gap-1 no-wrap self-end"):
                if item.envelopes:
                    with ui.row().classes("acoes-balao items-center gap-0 no-wrap"):
                        ui.button(icon="biotech", on_click=lambda m=item.message_id: ui.navigate.to(f"/inspetor?mensagem={m}")).props(
                            "flat round dense size=xs color=grey-8"
                        ).tooltip("Ver a criptografia passo a passo")
                        ui.button(icon="route", on_click=lambda m=item.message_id: ui.navigate.to(f"/caminho?mensagem={m}")).props(
                            "flat round dense size=xs color=grey-8"
                        ).tooltip("Ver o caminho pela rede")
                ui.label(hora(item.sent_at)).classes("text-[11px] text-slate-500")
                icone, cor = _icone_status(item)
                with ui.icon(icone).classes(f"text-sm {cor}"):
                    ui.tooltip(_status(item))
        problema = _problema(item)
        if problema:
            texto, cor = problema
            ui.label(texto).classes(f"text-xs px-2 {cor}")


def _icone_status(item: ItemMensagem) -> tuple[str, str]:
    if item.status in ("rejeitada", "erro"):
        return "error", "text-red-700"
    if item.status == "verificada":
        return "verified", "text-emerald-700"
    if item.status == "entregue":
        return "done_all", "text-sky-700"
    if item.sem_rota:
        return "schedule", "text-amber-700"
    if item.status == "enviando":
        return "hourglass_top", "text-slate-500"
    return "done", "text-slate-500"


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


def _problema(item: ItemMensagem) -> tuple[str, str] | None:
    """O que precisa aparecer sem passar o mouse: falhas e mensagens paradas na fila."""
    if item.status in ("rejeitada", "erro"):
        return _status(item), "text-red-700"
    if item.sem_rota and item.status not in ("entregue", "verificada"):
        return _status(item), "text-amber-800"
    return None


def _dialogo_seguranca(mensageiro: Mensageiro, conversa: ConversaLocal) -> None:
    """Fingerprints conhecidos dos participantes: compare o número de segurança pessoalmente."""
    with ui.dialog() as dialogo, cartao("max-w-2xl p-5"):
        ui.label("Números de segurança").classes("text-lg font-bold")
        ui.label(
            "Compare com o que aparece no aparelho de cada pessoa. Se for diferente, o servidor pode ter trocado a chave "
            "(ataque man-in-the-middle)."
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
                    numero_seguranca(calcular_numero_seguranca(fingerprint))
                    ui.label(formatar_fingerprint(fingerprint)).classes("font-mono text-[11px] text-slate-400")
        ui.button("Fechar", on_click=dialogo.close).props("flat no-caps")
    dialogo.open()
