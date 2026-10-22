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
                        ui.label("Mensagens").classes("text-base font-bold text-stone-800 grow")
                        seguir = ui.switch("mais recente", value=estado["seguir"]).props("dense").classes("text-xs text-stone-600")
                        seguir.tooltip("Acompanhar sempre a mensagem mais recente")
                    with ui.scroll_area().style("height: calc(100vh - 250px)").classes("w-full"):

                        @ui.refreshable
                        def lista() -> None:
                            itens = mensagens_com_envelope(mensageiro)
                            if not itens:
                                ui.label("Nenhuma mensagem ainda.").classes("text-sm text-stone-500 px-1")
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
                            with ui.row().classes("w-full items-center gap-3 px-4 py-3 border-b border-stone-200"):
                                if escolha is None:
                                    ui.label("Topologia da rede").classes("font-bold txt-tinta")
                                    return
                                conversa, item = escolha
                                destinos = _destinatarios(conversa, item)
                                avatar(item.remetente, tamanho=8)
                                ui.label(f"@{item.remetente}").classes("font-semibold txt-tinta")
                                ui.icon("arrow_forward", color="grey-6")
                                if len(destinos) > 1:
                                    ui.toggle({p: f"@{p}" for p in destinos}, value=destinatario(conversa, item),
                                              on_change=lambda e: escolher_para(e.value)).props(
                                        "dense no-caps rounded unelevated color=white text-color=primary "
                                        "toggle-color=primary toggle-text-color=white"
                                    ).classes("ring-1 ring-stone-200 rounded-full").mark("caminho-destinatario")
                                else:
                                    avatar(destinos[0], tamanho=8)
                                    ui.label(f"@{destinos[0]}").classes("font-semibold txt-tinta")
                                if item.texto is not None:
                                    ui.label(f"“{encurtar(item.texto, 40)}”").classes("text-sm text-stone-500 italic truncate")
                                ui.space()
                                selo_modo(conversa.modo)
                                ui.button("Ver a criptografia", icon="biotech",
                                          on_click=lambda: ui.navigate.to(f"/inspetor?mensagem={item.message_id}")).props(
                                    "flat dense no-caps color=primary"
                                )

                        topo()
                        grafico = ui.echart({"series": []}).classes("w-full").style("height: 440px")
                        with ui.row().classes("w-full items-center gap-4 px-4 py-2 border-t border-stone-100"):
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
                            with ui.row().classes("items-center gap-2 no-wrap rounded-xl fundo-menta px-3 py-2"):
                                ui.icon("lock", color="positive")
                                ui.label(
                                    f"Em cada nó o envelope continua cifrado: só a chave privada de @{para_quem}, "
                                    "guardada no aparelho dele, abre a mensagem."
                                ).classes("text-sm txt-ok")

                    trilha()

            def mudou(parte: str, assinatura) -> bool:
                """Cada parte só é refeita quando o que ela mostra muda: refazer à toa reinicia as animações."""
                if estado.get(parte) == assinatura:
                    return False
                estado[parte] = assinatura
                return True

            def redesenhar() -> None:
                escolha = selecionada()
                message_id = escolha[1].message_id if escolha else None
                if mudou("v_lista", (mensageiro.versao, message_id)):
                    lista.refresh()
                para_quem = destinatario(*escolha) if escolha else None
                p = inspecao.percurso(estado["rede"], para_quem) if escolha else None
                if mudou("v_topo", (message_id, para_quem)):
                    topo.refresh()
                situacao = p and (tuple(p.nos), p.status, p.parado_em, p.confirmado)
                if mudou("v_trilha", (message_id, para_quem, bool(estado["rede"]), situacao)):
                    trilha.refresh()
                topologia: TopologiaOut | None = estado["topologia"]
                if topologia is None:
                    return
                if escolha is None or not estado["rede"]:
                    opcoes = diagrama.opcoes(topologia)
                else:
                    item = escolha[1]
                    adulterado = not item.propria and item.status == "rejeitada"  # só quem recebe percebe
                    opcoes = diagrama.opcoes(topologia, p.caminho, item.remetente, para_quem, p.status, adulterado)
                if mudou("desenho", json.dumps(opcoes, sort_keys=True, default=str)):
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
            ui.label(texto).classes("text-xs text-stone-600")
    with ui.row().classes("items-center gap-1 no-wrap"):
        ui.element("span").classes("inline-block w-4 h-3 rounded").style(f"background:{diagrama.COR_NO_DESLIGADO}")
        ui.label("nó desligado").classes("text-xs text-stone-600")


def trilha_percurso(remetente: str, p: Percurso, com_rastro: bool = True) -> None:
    """@remetente → nós → @destinatário: as estações surgem em sequência e o cifrado "corre" pelas conexões."""
    estacoes: list[tuple[str, str, str, str]] = [("person", f"@{remetente}", "escreveu e cifrou", "marca")]
    if p.status == "sem_rota":
        estacoes.append(("dns", p.parado_em or "relay", "esperando um caminho", "alerta"))
    elif p.nos:
        estacoes += [("dns", no, "repassa o cifrado", "neutro") for no in p.nos]
    elif com_rastro:
        estacoes.append(("dns", "servidor", "relay central", "neutro"))
    if not com_rastro:
        final = ("a caminho", "info")
    elif p.status == "entregue":
        final = ("recebeu e confirmou" if p.confirmado else "recebeu", "ok")
    elif p.status == "offline":
        final = ("offline: espera na fila", "alerta")
    elif p.status == "sem_rota":
        final = ("sem caminho até aqui", "erro")
    else:
        final = ("a caminho", "info")
    estacoes.append(("person", f"@{p.para}", *final))

    ultima = len(estacoes) - 1
    with ui.row().classes("w-full items-start gap-1 flex-wrap"):
        for i, (icone, nome, legenda_estacao, tom) in enumerate(estacoes):
            atraso = i * 0.18
            if i:
                if i == ultima and p.status == "sem_rota":
                    tipo = "parado"
                elif i == ultima and p.status == "offline":
                    tipo = "fila"
                else:
                    tipo = "fluxo"
                _conexao(tipo, atraso - 0.09)
            chegou = i == ultima and com_rastro and p.status == "entregue"
            with ui.column().classes("items-center gap-1 w-24 surgir").style(f"animation-delay: {atraso:.2f}s"):
                with ui.element("div").classes(f"rounded-full p-2 ring-1 flex {TONS[tom]} {'pulso' if chegou else ''}"):
                    ui.icon(icone).classes("text-xl")
                ui.label(nome).classes("text-sm font-semibold txt-tinta text-center quebra leading-tight")
                ui.label(legenda_estacao).classes("text-[11px] text-stone-500 text-center leading-tight")


def _conexao(tipo: str, atraso: float) -> None:
    """fluxo: o cifrado passando (animado); fila: parado esperando o destinatário; parado: sem caminho."""
    with ui.column().classes("items-center gap-0.5 mt-1 surgir").style(f"animation-delay: {max(atraso, 0):.2f}s"):
        if tipo == "parado":
            ui.icon("block", color="negative").classes("text-sm")
        else:
            ui.icon("lock", color="positive" if tipo == "fluxo" else "warning").classes("text-sm")
        ui.element("div").classes("w-12 " + {"fluxo": "fluxo", "fila": "fluxo-fila", "parado": "fluxo-parado"}[tipo])
