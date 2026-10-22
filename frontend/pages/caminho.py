"""Caminho da mensagem: por quais nós o envelope de cada mensagem passou, desenhado sobre a topologia.

Usa só o que qualquer participante pode pedir ao servidor: a topologia e o rastro de trânsito da própria
mensagem (GET /api/trace). Os nós só repassam o cifrado — o texto não aparece aqui. O Observador (só
administradores) mostra o mesmo desenho para o tráfego de todos.
"""

from __future__ import annotations

import json

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import inspecao
from frontend.api_client import ErroApi
from frontend.inspecao import Percurso
from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro
from frontend.pages import diagrama
from frontend.pages.layout import (
    TONS,
    avatar,
    cartao,
    conectar,
    encurtar,
    item_mensagem,
    mensagens_com_envelope,
    moldura,
    selo_modo,
    titulo_pagina,
    vazio,
)
from frontend.sessao import Sessao
from shared.schemas import EventoTransitoOut, TopologiaOut

TOPOLOGIA_A_CADA = 4  # segundos entre releituras da topologia (clientes entrando e saindo, nós ligados)


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/caminho")
    async def pagina(mensagem: str | None = None, para: str | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        estado: dict = {"mensagem": mensagem, "para": para, "seguir": mensagem is None, "rede": [], "topologia": None}

        def selecionada() -> tuple[ConversaLocal, ItemMensagem] | None:
            if not estado["seguir"] and estado["mensagem"] is not None:
                encontrada = mensageiro.mensagem(estado["mensagem"])
                if encontrada is not None and encontrada[1].envelopes:
                    return encontrada
            itens = mensagens_com_envelope(mensageiro)
            return itens[0] if itens else None

        def destinatario(conversa: ConversaLocal, item: ItemMensagem) -> str:
            destinos = _destinatarios(conversa, item)
            if estado["para"] in destinos:
                return estado["para"]
            return mensageiro.eu if mensageiro.eu in destinos else destinos[0]

        async def carregar() -> None:
            escolha = selecionada()
            try:
                estado["topologia"] = await sessao.api.topologia()
                estado["rede"] = await sessao.api.rastro(escolha[1].message_id) if escolha else []
            except (ErroApi, httpx.HTTPError):
                pass  # mantém o último desenho; o indicador do cabeçalho mostra a conexão

        await carregar()

        with moldura(sessao, mensageiro, "/caminho") as conteudo:
            conteudo.classes("max-w-none")
            titulo_pagina("Caminho da mensagem", "Por onde o envelope cifrado passa até chegar a cada destinatário.", "route")

            with ui.row().classes("w-full gap-4 no-wrap items-start max-lg:flex-wrap"):
                with cartao("w-80 shrink-0 max-lg:w-full gap-1 p-3"):
                    with ui.row().classes("w-full items-center no-wrap px-1"):
                        ui.label("Mensagens").classes("text-base font-bold text-slate-800 grow")
                        seguir = ui.switch("mais recente", value=estado["seguir"]).props("dense").classes("text-xs text-slate-600")
                        seguir.tooltip("Acompanhar sempre a mensagem mais recente")
                    with ui.scroll_area().style("height: calc(100vh - 250px)").classes("w-full"):

                        @ui.refreshable
                        def lista() -> None:
                            itens = mensagens_com_envelope(mensageiro)
                            if not itens:
                                ui.label("Nenhuma mensagem ainda.").classes("text-sm text-slate-500 px-1")
                            atual = selecionada()
                            for conversa, item in itens:
                                item_mensagem(
                                    conversa, item, atual is not None and item is atual[1],
                                    lambda m=item.message_id: escolher(m),
                                )

                        lista()

                with ui.column().classes("grow gap-4 min-w-0"):
                    with cartao("w-full p-0 gap-0 overflow-hidden"):

                        @ui.refreshable
                        def topo() -> None:
                            escolha = selecionada()
                            with ui.row().classes("w-full items-center gap-3 px-4 py-3 border-b border-slate-200"):
                                if escolha is None:
                                    ui.label("Topologia da rede").classes("font-bold text-slate-800")
                                    return
                                conversa, item = escolha
                                destinos = _destinatarios(conversa, item)
                                avatar(item.remetente, tamanho=8)
                                ui.label(f"@{item.remetente}").classes("font-semibold")
                                ui.icon("arrow_forward", color="grey-6")
                                if len(destinos) > 1:
                                    ui.toggle({p: f"@{p}" for p in destinos}, value=destinatario(conversa, item),
                                              on_change=lambda e: escolher_para(e.value)).props(
                                        "dense no-caps unelevated toggle-color=primary"
                                    ).mark("caminho-destinatario")
                                else:
                                    avatar(destinos[0], tamanho=8)
                                    ui.label(f"@{destinos[0]}").classes("font-semibold")
                                if item.texto is not None:
                                    ui.label(f"“{encurtar(item.texto, 40)}”").classes("text-sm text-slate-500 italic truncate")
                                ui.space()
                                selo_modo(conversa.modo)
                                ui.button("Ver a criptografia", icon="biotech",
                                          on_click=lambda: ui.navigate.to(f"/inspetor?mensagem={item.message_id}")).props(
                                    "flat dense no-caps color=primary"
                                )

                        topo()
                        grafico = ui.echart({"series": []}).classes("w-full").style("height: 440px")
                        with ui.row().classes("w-full items-center gap-4 px-4 py-2 border-t border-slate-100"):
                            legenda()

                    @ui.refreshable
                    def trilha() -> None:
                        escolha = selecionada()
                        with cartao("w-full p-5 gap-4"):
                            if escolha is None:
                                vazio("route", "Envie uma mensagem pelo chat e volte aqui para ver o caminho dela.")
                                return
                            conversa, item = escolha
                            para_quem = destinatario(conversa, item)
                            ui.label("Etapas do percurso").classes("rotulo")
                            trilha_percurso(item.remetente, inspecao.percurso(estado["rede"], para_quem), bool(estado["rede"]))
                            with ui.row().classes("items-center gap-2 no-wrap rounded-xl bg-emerald-50 px-3 py-2"):
                                ui.icon("lock", color="positive")
                                ui.label(
                                    f"Em cada nó o envelope continua cifrado: só a chave privada de @{para_quem}, "
                                    "guardada no aparelho dele, abre a mensagem."
                                ).classes("text-sm text-emerald-900")

                    trilha()

            def redesenhar() -> None:
                lista.refresh()
                topo.refresh()
                trilha.refresh()
                topologia: TopologiaOut | None = estado["topologia"]
                if topologia is None:
                    return
                escolha = selecionada()
                if escolha is None or not estado["rede"]:
                    opcoes = diagrama.opcoes(topologia)
                else:
                    conversa, item = escolha
                    para_quem = destinatario(conversa, item)
                    p = inspecao.percurso(estado["rede"], para_quem)
                    adulterado = not item.propria and item.status == "rejeitada"  # só quem recebe percebe
                    opcoes = diagrama.opcoes(topologia, p.caminho, item.remetente, para_quem, p.status, adulterado)
                # o ECharts reinicia a animação a cada atualização: só redesenha quando algo mudou
                assinatura = json.dumps(opcoes, sort_keys=True, default=str)
                if assinatura != estado.get("desenho"):
                    estado["desenho"] = assinatura
                    grafico.options.clear()
                    grafico.options.update(opcoes)
                    grafico.update()

            async def escolher(message_id: str) -> None:
                estado.update(mensagem=message_id, para=None, seguir=False)
                seguir.set_value(False)
                await carregar()
                redesenhar()

            def escolher_para(username: str) -> None:
                estado["para"] = username
                redesenhar()

            async def mudar_seguir(e) -> None:
                if e.value == estado["seguir"]:
                    return
                estado["seguir"] = e.value
                await carregar()
                redesenhar()

            seguir.on_value_change(mudar_seguir)

            relogio = {"versao": mensageiro.versao, "tique": 0}

            async def atualizar() -> None:
                relogio["tique"] += 1
                mudou = mensageiro.versao != relogio["versao"]
                escolha = selecionada()
                pendente = escolha is not None and _pendente(escolha, estado["rede"])
                if not (mudou or pendente or relogio["tique"] % TOPOLOGIA_A_CADA == 0):
                    return
                relogio["versao"] = mensageiro.versao
                await carregar()
                redesenhar()

            ui.timer(1.0, atualizar)
            redesenhar()


def _destinatarios(conversa: ConversaLocal, item: ItemMensagem) -> list[str]:
    return [p for p in conversa.participantes if p != item.remetente]


def _pendente(escolha: tuple[ConversaLocal, ItemMensagem], rede: list[EventoTransitoOut]) -> bool:
    """Algum destinatário ainda não recebeu: vale reler o rastro a cada segundo."""
    conversa, item = escolha
    return not rede or any(inspecao.percurso(rede, p).status != "entregue" for p in _destinatarios(conversa, item))


# ---------------------------------------------------------------- componentes (também usados pelo Inspetor e pelo Observador)


def legenda() -> None:
    for cor, texto in ((diagrama.COR_CIFRADO, "envelope cifrado"), (diagrama.COR_FILA, "na fila"), (diagrama.COR_ADULTERADO, "adulterado")):
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.element("span").classes("inline-block w-3 h-3 rounded-full").style(f"background:{cor}")
            ui.label(texto).classes("text-xs text-slate-600")
    with ui.row().classes("items-center gap-1 no-wrap"):
        ui.element("span").classes("inline-block w-4 h-3 rounded bg-slate-300")
        ui.label("nó desligado").classes("text-xs text-slate-600")


def trilha_percurso(remetente: str, p: Percurso, com_rastro: bool = True) -> None:
    """@remetente → nós → @destinatário, com a situação da entrega no fim."""
    estacoes: list[tuple[str, str, str, str]] = [("person", f"@{remetente}", "escreveu e cifrou", "teal")]
    if p.status == "sem_rota":
        estacoes.append(("dns", p.parado_em or "relay", "esperando um caminho", "ambar"))
    elif p.nos:
        estacoes += [("dns", no, "repassa o cifrado", "cinza") for no in p.nos]
    elif com_rastro:
        estacoes.append(("dns", "servidor", "relay central", "cinza"))
    if not com_rastro:
        final = ("a caminho", "azul")
    elif p.status == "entregue":
        final = ("recebeu e confirmou" if p.confirmado else "recebeu", "verde")
    elif p.status == "offline":
        final = ("offline: espera na fila", "ambar")
    elif p.status == "sem_rota":
        final = ("sem caminho até aqui", "vermelho")
    else:
        final = ("a caminho", "azul")
    estacoes.append(("person", f"@{p.para}", *final))

    with ui.row().classes("w-full items-start gap-1 flex-wrap"):
        for i, (icone, nome, legenda_estacao, tom) in enumerate(estacoes):
            if i:
                bloqueado = p.status == "sem_rota" and i == len(estacoes) - 1
                _conexao(bloqueado)
            with ui.column().classes("items-center gap-1 w-24"):
                with ui.element("div").classes(f"rounded-full p-2 ring-1 flex {TONS[tom]}"):
                    ui.icon(icone).classes("text-xl")
                ui.label(nome).classes("text-sm font-semibold text-slate-800 text-center break-all leading-tight")
                ui.label(legenda_estacao).classes("text-[11px] text-slate-500 text-center leading-tight")


def _conexao(bloqueada: bool) -> None:
    with ui.row().classes("items-center gap-0 no-wrap mt-3"):
        linha = "border-dashed border-red-300" if bloqueada else "border-solid border-slate-300"
        ui.element("div").classes(f"w-4 border-t-2 {linha}")
        if bloqueada:
            ui.icon("block", color="negative").classes("text-base")
        else:
            ui.icon("lock", color="positive").classes("text-base")
        ui.element("div").classes(f"w-4 border-t-2 {linha}")
