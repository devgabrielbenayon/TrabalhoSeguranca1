"""Tela de chat: conversas 1:1 e em grupo, envio e recebimento em tempo real."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import background_tasks, ui

from frontend.api_client import ErroApi
from frontend.mensageiro import REMETENTE_SISTEMA, ConversaLocal, ErroEnvio, ItemMensagem, Mensageiro
from frontend.pages.layout import (
    ICONE_MODO,
    NOME_MODO,
    avatar,
    cartao,
    conectar,
    encurtar,
    hora,
    mensagem_erro,
    moldura,
    numero_seguranca,
    pilula,
    selo_modo,
    vazio,
)
from frontend.sessao import Sessao
from shared.crypto.base import formatar_fingerprint
from shared.crypto.base import numero_seguranca as calcular_numero_seguranca
from shared.crypto.blocos import MAX_TEXTO_CARACTERES, MensagemGrandeDemais
from shared.schemas import ClienteOut

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
        clientes = await _outros_clientes(sessao)
        conteudo = moldura(sessao, mensageiro, "/chat")

        estado = {"atual": conversa if conversa in mensageiro.conversas else _mais_recente(mensageiro)}
        nomes = {c.username: c.nome for c in clientes}

        def selecionar(conversation_id: int) -> None:
            estado["atual"] = conversation_id
            lista.refresh()
            cabecalho_conversa.refresh()
            mensagens.refresh()
            rolar_para_o_fim()

        abrir_nova = _dialogo_nova_conversa(sessao, mensageiro, clientes, selecionar)

        with conteudo.classes("max-w-none"):
            with ui.row().classes("w-full no-wrap gap-4 items-stretch").style("height: calc(100vh - 112px); min-height: 460px"):
                # ---------------------------------------------------- coluna das conversas
                with cartao("w-80 shrink-0 gap-3 p-3"):
                    with ui.row().classes("w-full items-center no-wrap px-1"):
                        ui.label("Conversas").classes("text-lg font-bold txt-tinta grow")
                        ui.button(icon="add", on_click=abrir_nova).props("round unelevated color=primary size=sm").tooltip(
                            "Nova conversa"
                        ).mark("chat-nova")
                    filtro = ui.input(placeholder="Buscar conversa").props("outlined dense rounded clearable").classes("w-full")
                    with filtro.add_slot("prepend"):
                        ui.icon("search", color="grey-6")
                    filtro.on_value_change(lambda: lista.refresh())
                    with ui.scroll_area().classes("w-full grow min-h-0"):

                        @ui.refreshable
                        def lista() -> None:
                            if not mensageiro.conversas:
                                with ui.column().classes("w-full items-center gap-2 py-10 text-center"):
                                    ui.icon("forum", color="grey-5").classes("text-5xl")
                                    ui.label("Nenhuma conversa ainda.").classes("text-sm text-stone-500")
                                    ui.button("Começar uma", icon="add", on_click=abrir_nova).props("flat no-caps color=primary")
                                return
                            termo = (filtro.value or "").strip().lower().lstrip("@")
                            ordem = sorted(mensageiro.conversas.values(), key=_atividade, reverse=True)
                            visiveis = [c for c in ordem if not termo or _combina(c, termo, nomes, sessao.usuario.username)]
                            if not visiveis:
                                ui.label("Nenhuma conversa com esse nome.").classes("text-sm text-stone-500 px-1")
                            with ui.column().classes("w-full gap-1"):
                                for c in visiveis:
                                    if c.id == estado["atual"]:
                                        c.nao_lidas = 0
                                    _item_lista(sessao, c, nomes, c.id == estado["atual"], lambda c=c: selecionar(c.id))

                        lista()

                # ---------------------------------------------------- conversa aberta
                with cartao("grow min-w-0 p-0 gap-0 overflow-hidden"):

                    @ui.refreshable
                    def cabecalho_conversa() -> None:
                        atual = mensageiro.conversas.get(estado["atual"])
                        if atual is None:
                            return
                        outros = [p for p in atual.participantes if p != sessao.usuario.username]
                        with ui.row().classes("items-center gap-3 w-full no-wrap px-4 py-3 border-b border-stone-200 bg-white"):
                            if atual.tipo == "grupo":
                                _avatares_grupo(outros)
                            else:
                                avatar(outros[0] if outros else "?")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                with ui.row().classes("items-baseline gap-2 no-wrap"):
                                    ui.label(_titulo(atual, outros, nomes)).classes("text-base font-bold txt-tinta truncate")
                                    if atual.tipo != "grupo" and outros:
                                        ui.label(f"@{outros[0]}").classes("text-xs text-stone-400")
                                with ui.row().classes("items-center gap-1 no-wrap"):
                                    ui.icon("lock", color="positive").classes("text-sm")
                                    ui.label(f"Criptografia ponta a ponta · {MODOS[atual.modo]}").classes("text-xs text-stone-500")
                            ui.button(icon="verified_user", on_click=lambda: _dialogo_seguranca(mensageiro, atual)).props(
                                "flat round color=primary"
                            ).tooltip("Números de segurança")

                    cabecalho_conversa()

                    with ui.scroll_area().classes("w-full grow min-h-0").style("background: #fbf8f4") as area:

                        @ui.refreshable
                        def mensagens() -> None:
                            atual = mensageiro.conversas.get(estado["atual"])
                            if atual is None:
                                vazio("forum", "Selecione uma conversa ou crie uma nova")
                                with ui.row().classes("w-full justify-center"):
                                    ui.button("Nova conversa", icon="add", on_click=abrir_nova).props("unelevated no-caps")
                                return
                            if not atual.mensagens:
                                vazio("lock", "Nenhuma mensagem ainda. A primeira já sai cifrada e assinada.")
                            with ui.column().classes("w-full gap-2 px-2 py-3"):
                                for item in atual.ordenadas():
                                    _balao(item, atual.tipo == "grupo")

                        mensagens()

                    def rolar_para_o_fim() -> None:
                        ui.timer(0.05, lambda: area.scroll_to(percent=1.0), once=True)

                    with ui.row().classes("w-full items-center no-wrap gap-2 px-3 py-3 border-t border-stone-200 bg-white"):
                        texto = ui.input(placeholder="Escreva uma mensagem").classes("grow").props(
                            f"outlined dense rounded maxlength={MAX_TEXTO_CARACTERES}"
                        ).mark("chat-texto")
                        contador = ui.label().classes("text-xs text-stone-400 w-32 text-right shrink-0")
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


async def _outros_clientes(sessao: Sessao) -> list[ClienteOut]:
    """Quem pode entrar numa conversa: os outros clientes ativos, online primeiro."""
    try:
        clientes = await sessao.api.clientes()
    except (ErroApi, httpx.HTTPError):
        return []
    outros = [c for c in clientes if c.ativo and c.username != sessao.usuario.username]
    return sorted(outros, key=lambda c: (not c.online, c.nome.lower()))


def _atividade(conversa: ConversaLocal) -> str:
    ultima = conversa.ultima()
    return ultima.sent_at if ultima else ""


def _mais_recente(mensageiro: Mensageiro) -> int | None:
    if not mensageiro.conversas:
        return None
    return max(mensageiro.conversas.values(), key=lambda c: (_atividade(c), c.id)).id


def _titulo(conversa: ConversaLocal, outros: list[str], nomes: dict[str, str]) -> str:
    """O nome de quem está do outro lado (ou dos membros do grupo); o @usuário quando o nome não é conhecido."""
    if conversa.tipo == "grupo":
        return ", ".join(nomes.get(p, p).split()[0] for p in outros)
    return nomes.get(outros[0], f"@{outros[0]}") if outros else "?"


def _combina(conversa: ConversaLocal, termo: str, nomes: dict[str, str], eu: str) -> bool:
    return any(termo in p or termo in nomes.get(p, "").lower() for p in conversa.participantes if p != eu)


def _avatares_grupo(outros: list[str], tamanho: int = 10) -> None:
    """Dois avatares sobrepostos (os primeiros membros) representando o grupo."""
    px = tamanho * 4
    with ui.element("div").classes("relative shrink-0").style(f"width:{px}px;height:{px}px"):
        with ui.element("div").classes("absolute top-0 left-0"):
            avatar(outros[0] if outros else "?", tamanho=tamanho * 2 // 3)
        with ui.element("div").classes("absolute bottom-0 right-0 rounded-full ring-2 ring-white"):
            avatar(outros[1] if len(outros) > 1 else "+", tamanho=tamanho * 2 // 3)


def _item_lista(sessao: Sessao, conversa: ConversaLocal, nomes: dict[str, str], selecionada: bool, ao_clicar) -> None:
    outros = [p for p in conversa.participantes if p != sessao.usuario.username]
    ultima = conversa.ultima()
    estado = "selecionado" if selecionada else "clicavel"
    with ui.row().classes(f"w-full rounded-xl p-2 cursor-pointer no-wrap items-center gap-3 {estado}").on("click", ao_clicar):
        if conversa.tipo == "grupo":
            _avatares_grupo(outros)
        else:
            avatar(outros[0] if outros else "?")
        with ui.column().classes("gap-0.5 grow min-w-0"):
            with ui.row().classes("items-center gap-1.5 no-wrap w-full"):
                ui.label(_titulo(conversa, outros, nomes)).classes("font-semibold txt-tinta truncate grow")
                selo_modo(conversa.modo)
            with ui.row().classes("items-center gap-1 no-wrap w-full"):
                previa = "sem mensagens" if ultima is None else (
                    ("você: " if ultima.propria else "") + (ultima.texto if ultima.texto is not None else "[não foi possível ler]")
                )
                ui.label(encurtar(previa, 40)).classes("text-xs text-stone-500 truncate grow")
                if conversa.nao_lidas:
                    ui.badge(str(conversa.nao_lidas)).props("rounded color=accent text-color=primary")
                elif ultima:
                    ui.label(hora(ultima.sent_at)).classes("text-[11px] text-stone-400 shrink-0")


# ---------------------------------------------------------------- nova conversa


def _dialogo_nova_conversa(sessao: Sessao, mensageiro: Mensageiro, clientes: list[ClienteOut], ao_criar):
    """Escolher as pessoas numa lista (com busca, status e o nó de cada uma) e o modo. Devolve a função que abre."""
    escolha: dict = {"modo": "real", "pessoas": [], "clientes": clientes}
    opcoes: dict[str, ui.element] = {}

    def classes_opcao(marcada: bool) -> str:
        cores = "ring-2 ring-[#45324d] fundo-pessego" if marcada else "ring-1 ring-stone-200 clicavel"
        return f"flex flex-col grow basis-0 gap-0.5 p-3 rounded-xl cursor-pointer {cores}"

    def escolher_modo(modo: str) -> None:
        escolha["modo"] = modo
        for chave, opcao in opcoes.items():
            opcao.classes(replace=classes_opcao(chave == modo))
        pessoas.refresh()

    def alternar(username: str) -> None:
        if username in escolha["pessoas"]:
            escolha["pessoas"].remove(username)
        else:
            escolha["pessoas"].append(username)
        pessoas.refresh()
        escolhidas.refresh()
        criar_botao.set_enabled(bool(escolha["pessoas"]))

    with ui.dialog() as dialogo, cartao("w-[520px] max-w-full gap-3 p-5"):
        with ui.row().classes("w-full items-center no-wrap"):
            with ui.column().classes("gap-0 grow"):
                ui.label("Nova conversa").classes("text-lg font-bold txt-tinta")
                ui.label("Escolha uma pessoa, ou várias para criar um grupo.").classes("text-xs text-stone-500")
            ui.button(icon="close", on_click=dialogo.close).props("flat round dense color=grey-7")
        busca = ui.input(placeholder="Buscar por nome ou usuário").props("outlined dense rounded clearable").classes(
            "w-full"
        ).mark("chat-busca")
        with busca.add_slot("prepend"):
            ui.icon("search", color="grey-6")
        busca.on_value_change(lambda: pessoas.refresh())

        @ui.refreshable
        def escolhidas() -> None:
            if not escolha["pessoas"]:
                return
            with ui.row().classes("w-full items-center gap-1"):
                for username in escolha["pessoas"]:
                    ui.chip(f"@{username}", removable=True, on_value_change=lambda _, u=username: alternar(u)).props(
                        "dense color=accent text-color=primary"
                    )

        escolhidas()

        with ui.scroll_area().classes("w-full rounded-xl ring-1 ring-stone-200").style("height: 248px"):

            @ui.refreshable
            def pessoas() -> None:
                termo = (busca.value or "").strip().lower().lstrip("@")
                visiveis = [c for c in escolha["clientes"] if not termo or termo in c.username or termo in c.nome.lower()]
                if not escolha["clientes"]:
                    ui.label("Ninguém mais se cadastrou ainda.").classes("text-sm text-stone-500 p-2")
                elif not visiveis:
                    ui.label("Ninguém encontrado com esse nome.").classes("text-sm text-stone-500 p-2")
                with ui.column().classes("w-full gap-1"):
                    for cliente in visiveis:
                        _linha_pessoa(cliente, cliente.username in escolha["pessoas"], escolha["modo"],
                                      lambda u=cliente.username: alternar(u))

            pessoas()

        ui.label("Criptografia").classes("rotulo mt-1")
        with ui.row().classes("w-full gap-2 no-wrap"):
            for modo, (titulo, explicacao) in OPCOES_MODO.items():
                with ui.element("div").classes(classes_opcao(modo == "real")).on(
                    "click", lambda m=modo: escolher_modo(m)
                ).mark(f"chat-modo-{modo}") as opcao:
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon(ICONE_MODO[modo], color="primary")
                        ui.label(titulo).classes("font-bold text-sm txt-tinta")
                    ui.label(explicacao).classes("text-xs text-stone-600")
                opcoes[modo] = opcao

        async def criar() -> None:
            if not escolha["pessoas"]:
                return
            try:
                nova = await mensageiro.nova_conversa(list(escolha["pessoas"]), escolha["modo"])
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            dialogo.close()
            ao_criar(nova.id)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat no-caps")
            criar_botao = ui.button("Criar conversa", icon="add_comment", on_click=criar).props("unelevated no-caps").mark(
                "chat-criar"
            )
            criar_botao.disable()

    async def recarregar() -> None:
        escolha["clientes"] = await _outros_clientes(sessao) or escolha["clientes"]
        pessoas.refresh()

    def abrir() -> None:
        """Zera a escolha na hora; a lista de pessoas (status online) é relida em segundo plano."""
        escolha["pessoas"].clear()
        busca.value = ""
        escolhidas.refresh()
        pessoas.refresh()
        criar_botao.disable()
        dialogo.open()
        background_tasks.create(recarregar(), name="recarregar-pessoas")

    return abrir


def _linha_pessoa(cliente: ClienteOut, marcada: bool, modo: str, ao_clicar) -> None:
    estado = "selecionado" if marcada else "clicavel"
    with ui.row().classes(f"w-full items-center gap-3 no-wrap rounded-xl px-2 py-2 cursor-pointer {estado}").on(
        "click", ao_clicar
    ).mark(f"chat-contato-{cliente.username}"):
        avatar(cliente.username, cliente.avatar, tamanho=9, online=cliente.online)
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(cliente.nome).classes("text-sm font-semibold txt-tinta truncate")
            detalhe = f"@{cliente.username}" + (f" · nó {cliente.servidor}" if cliente.servidor else "")
            ui.label(detalhe).classes("text-xs text-stone-500 truncate")
        if modo not in cliente.modos_ativos:
            pilula(f"sem chave {NOME_MODO[modo]}", "alerta").tooltip(
                "Esta pessoa não tem chave ativa neste modo: ainda não dá para cifrar para ela"
            )
        else:
            ui.label("online" if cliente.online else "offline").classes(
                "text-xs " + ("txt-ok font-medium" if cliente.online else "text-stone-400")
            )
        ui.icon("check_circle" if marcada else "radio_button_unchecked", color="primary" if marcada else "grey-5").classes(
            "text-xl shrink-0"
        )


# ---------------------------------------------------------------- mensagens


def _contar(contador: ui.label, valor: str | None) -> None:
    tamanho = len(valor or "")
    contador.text = f"{tamanho}/{MAX_TEXTO_CARACTERES} caracteres"
    cor = "txt-erro font-bold" if tamanho >= MAX_TEXTO_CARACTERES else "text-stone-400"
    contador.classes(replace=f"text-xs w-32 text-right shrink-0 {cor}")


def _balao(item: ItemMensagem, grupo: bool) -> None:
    if item.status == "aviso" or item.remetente == REMETENTE_SISTEMA:
        with ui.row().classes("w-full justify-center"):
            with ui.row().classes("items-start gap-2 no-wrap max-w-xl rounded-xl px-3 py-2 fundo-pessego ring-1 ring-[#edbf8a]"):
                ui.icon("key", color="warning").classes("text-base mt-0.5")
                ui.label(item.texto).classes("text-xs txt-alerta quebra")
        return
    descartada = item.texto is None
    cores = "balao-erro" if descartada else ("balao-meu" if item.propria else "balao-outro")
    canto = "rounded-br-md" if item.propria else "rounded-bl-md"
    with ui.column().classes("w-full gap-0.5 balao " + ("items-end" if item.propria else "items-start")):
        # min-w-0 + quebra: uma palavra enorme quebra dentro do balão em vez de vazar
        with ui.column().classes(f"min-w-0 gap-0.5 rounded-2xl {canto} px-3 py-2 {cores}").style("max-width: min(70%, 640px)"):
            if grupo and not item.propria:
                ui.label(f"@{item.remetente}").classes("text-xs font-bold txt-tinta")
            ui.label(item.texto if not descartada else "[mensagem descartada]").classes(
                "text-sm whitespace-pre-wrap quebra max-w-full " + ("txt-erro italic" if descartada else "text-stone-900")
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
                ui.label(hora(item.sent_at)).classes("text-[11px] text-stone-500")
                icone, cor = _icone_status(item)
                with ui.icon(icone).classes(f"text-sm {cor}"):
                    ui.tooltip(_status(item))
        problema = _problema(item)
        if problema:
            texto, cor = problema
            ui.label(texto).classes(f"text-xs px-2 quebra {cor}")


def _icone_status(item: ItemMensagem) -> tuple[str, str]:
    if item.status in ("rejeitada", "erro"):
        return "error", "txt-erro"
    if item.status == "verificada":
        return "verified", "txt-ok"
    if item.status == "entregue":
        return "done_all", "txt-ok"
    if item.sem_rota:
        return "schedule", "txt-alerta"
    if item.status == "enviando":
        return "hourglass_top", "text-stone-500"
    return "done", "text-stone-500"


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
        return _status(item), "txt-erro"
    if item.sem_rota and item.status not in ("entregue", "verificada"):
        return _status(item), "txt-alerta"
    return None


def _dialogo_seguranca(mensageiro: Mensageiro, conversa: ConversaLocal) -> None:
    """Fingerprints conhecidos dos participantes: compare o número de segurança pessoalmente."""
    with ui.dialog() as dialogo, cartao("max-w-2xl p-5"):
        ui.label("Números de segurança").classes("text-lg font-bold txt-tinta")
        ui.label(
            "Compare com o que aparece no aparelho de cada pessoa. Se for diferente, o servidor pode ter trocado a chave "
            "(ataque man-in-the-middle)."
        ).classes("text-sm text-stone-600")
        for participante in conversa.participantes:
            fingerprint = mensageiro.cache.conhecidas.get((participante, conversa.modo))
            if participante == mensageiro.eu and mensageiro.sessao.keystore:
                privada = mensageiro.sessao.keystore.ativa(conversa.modo)
                fingerprint = privada.publica.fingerprint if privada else None
            with ui.column().classes("gap-1 w-full border-b border-stone-100 py-2"):
                with ui.row().classes("items-center gap-2"):
                    avatar(participante, tamanho=7)
                    ui.label(f"@{participante}" + (" (você)" if participante == mensageiro.eu else "")).classes("font-bold")
                if fingerprint is None:
                    ui.label("ainda não buscada — envie uma mensagem primeiro").classes("text-xs text-stone-500")
                else:
                    numero_seguranca(calcular_numero_seguranca(fingerprint))
                    ui.label(formatar_fingerprint(fingerprint)).classes("font-mono text-[11px] text-stone-400")
        ui.button("Fechar", on_click=dialogo.close).props("flat no-caps")
    dialogo.open()
