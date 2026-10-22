"""CRUD de servidores/nós (RF13): topologia, liga/desliga, ligações entre nós e capacidade.

Desligar um nó do caminho faz o envelope desviar por outro; se não houver caminho, ele espera na fila
(relógio no chat) e sai sozinho quando um caminho voltar. Administradores alteram; os demais só veem.
"""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import events, ui

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages import diagrama
from frontend.pages.layout import conectar, mensagem_erro, moldura, secao, titulo_pagina
from frontend.sessao import Sessao
from shared.schemas import ServidorIn, ServidorOut, TopologiaOut


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/servidores")
    async def pagina():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        dados: dict = {"topologia": None, "assinatura": None}
        try:
            dados["topologia"] = await sessao.api.topologia()
            dados["assinatura"] = dados["topologia"].model_dump_json()
        except (ErroApi, httpx.HTTPError) as erro:
            ui.notify(mensagem_erro(erro), type="negative")
        with moldura(sessao, mensageiro, "/servidores"):
            titulo_pagina(
                "Servidores",
                "Nós lógicos de retransmissão: cada cliente fica num nó, e o envelope anda pelo caminho mais curto entre eles.",
                "dns",
            )

            async def carregar(forcar: bool = True) -> None:
                try:
                    topologia = await sessao.api.topologia()
                except (ErroApi, httpx.HTTPError) as erro:
                    if forcar:
                        ui.notify(mensagem_erro(erro), type="negative")
                    return
                assinatura = topologia.model_dump_json()
                if forcar or assinatura != dados["assinatura"]:
                    dados["topologia"], dados["assinatura"] = topologia, assinatura
                    conteudo.refresh()

            async def alternar(no: ServidorOut, ativo: bool) -> None:
                try:
                    await sessao.api.status_servidor(no.id, ativo)
                except (ErroApi, httpx.HTTPError) as erro:
                    ui.notify(mensagem_erro(erro), type="negative")
                else:
                    ui.notify(
                        f"Nó {no.nome} {'ligado' if ativo else 'desligado'}: caminhos recalculados",
                        type="positive" if ativo else "warning",
                    )
                await carregar()

            async def clique_no_grafico(e: events.EChartPointClickEventArguments) -> None:
                topologia: TopologiaOut | None = dados["topologia"]
                no = next((n for n in topologia.nos if n.nome == e.name), None) if topologia else None
                if no is not None and sessao.admin:
                    await alternar(no, not no.ativo)

            @ui.refreshable
            def conteudo() -> None:
                topologia: TopologiaOut | None = dados["topologia"]
                if topologia is None:
                    return
                with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
                    with secao(
                        "Topologia",
                        "hub",
                        "Clique num nó para ligar/desligar." if sessao.admin else "Nós ligados em verde-azulado; desligados em cinza.",
                    ).classes("grow basis-96"):
                        ui.echart(diagrama.opcoes(topologia), on_point_click=clique_no_grafico).classes("w-full").style("height: 420px")
                    with ui.column().classes("grow basis-96 gap-2"):
                        if not topologia.nos:
                            with secao("Nenhum nó cadastrado", "info", "Sem nós, o relay é central: o envelope vai direto do remetente ao destinatário."):
                                if sessao.admin:
                                    async def exemplo() -> None:
                                        try:
                                            await sessao.api.topologia_exemplo()
                                        except (ErroApi, httpx.HTTPError) as erro:
                                            ui.notify(mensagem_erro(erro), type="negative")
                                        await carregar()

                                    ui.button("Criar topologia de exemplo", icon="auto_awesome", on_click=exemplo).mark("servidor-exemplo")
                        nomes = {n.id: n.nome for n in topologia.nos}
                        for no in topologia.nos:
                            _cartao_no(sessao, no, nomes, topologia, alternar, carregar)
                        if sessao.admin:
                            ui.button("Novo nó", icon="add", on_click=lambda: _dialogo_no(sessao, None, topologia, carregar)).mark(
                                "servidor-novo"
                            )

            conteudo()
            ui.timer(3.0, lambda: carregar(forcar=False))  # clientes entrando/saindo e mudanças de outros administradores


def _cartao_no(sessao: Sessao, no: ServidorOut, nomes: dict[int, str], topologia: TopologiaOut, alternar, recarregar) -> None:
    online = {c.username for c in topologia.clientes if c.online}
    with ui.card().classes("w-full shadow-sm " + ("" if no.ativo else "bg-stone-50")):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.icon("dns", color="primary" if no.ativo else "grey-5").classes("text-2xl")
            with ui.column().classes("gap-0 grow min-w-0"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(no.nome).classes("font-bold")
                    ui.badge("ligado" if no.ativo else "desligado", color="positive" if no.ativo else "grey-6")
                ui.label(f"{no.regiao or 'sem região'} · {no.host}:{no.porta}").classes("text-xs text-stone-500")
            if sessao.admin:
                ui.switch(value=no.ativo, on_change=lambda e: alternar(no, e.value)).props("color=positive").mark(
                    f"servidor-ligado-{no.nome}"
                ).tooltip("Ligar/desligar (simula a queda do nó)")
                ui.button(icon="edit", on_click=lambda: _dialogo_no(sessao, no, topologia, recarregar)).props("flat round dense").mark(
                    f"servidor-editar-{no.nome}"
                )
                ui.button(icon="delete", on_click=lambda: _dialogo_remocao(sessao, no, recarregar)).props(
                    "flat round dense color=negative"
                ).mark(f"servidor-remover-{no.nome}")
        ocupacao = len(no.clientes) / max(no.capacidade, 1)
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.label(f"{len(no.clientes)}/{no.capacidade} clientes").classes("text-xs text-stone-600 w-28 shrink-0")
            ui.linear_progress(value=min(ocupacao, 1.0), show_value=False).props("rounded size=8px color=primary").classes("grow")
        with ui.row().classes("items-center gap-1 flex-wrap"):
            ui.label("Vizinhos:").classes("text-xs text-stone-500")
            for vizinho in no.vizinhos:
                ui.badge(nomes.get(vizinho, f"#{vizinho}"), color="grey-7").props("outline")
            if not no.vizinhos:
                ui.label("nenhum (isolado)").classes("text-xs txt-alerta")
        if no.clientes:
            with ui.row().classes("items-center gap-1 flex-wrap"):
                ui.label("Clientes:").classes("text-xs text-stone-500")
                for cliente in no.clientes:
                    ui.chip(f"@{cliente}", icon="circle" if cliente in online else "radio_button_unchecked").props(
                        f"dense outline {'color=positive' if cliente in online else ''}"
                    )


def _dialogo_no(sessao: Sessao, no: ServidorOut | None, topologia: TopologiaOut, recarregar) -> None:
    outros = {n.id: n.nome for n in topologia.nos if no is None or n.id != no.id}
    with ui.dialog() as dialogo, ui.card().classes("w-96"):
        ui.label("Novo nó" if no is None else f"Editar {no.nome}").classes("text-lg font-bold")
        nome = ui.input("Nome", value=no.nome if no else "").classes("w-full").mark("servidor-nome")
        regiao = ui.input("Região", value=no.regiao if no else "").classes("w-full").mark("servidor-regiao")
        with ui.row().classes("w-full no-wrap gap-2"):
            host = ui.input("Host", value=no.host if no else "127.0.0.1").classes("grow")
            porta = ui.number("Porta", value=no.porta if no else 9000, min=1, max=65535, format="%d").classes("w-28")
        capacidade = ui.number("Capacidade (clientes)", value=no.capacidade if no else 100, min=1, format="%d").classes("w-full")
        vizinhos = ui.select(outros, multiple=True, value=list(no.vizinhos) if no else [], label="Ligado a").classes(
            "w-full"
        ).props("use-chips").mark("servidor-vizinhos")
        ativo = ui.switch("Ligado", value=no.ativo if no else True)

        async def salvar() -> None:
            try:
                dados = ServidorIn(
                    nome=nome.value or "",
                    regiao=regiao.value or "",
                    host=host.value or "127.0.0.1",
                    porta=int(porta.value or 9000),
                    capacidade=int(capacidade.value or 100),
                    ativo=ativo.value,
                    vizinhos=list(vizinhos.value or []),
                )
                if no is None:
                    await sessao.api.criar_servidor(dados)
                else:
                    await sessao.api.editar_servidor(no.id, dados)
            except (ErroApi, httpx.HTTPError, ValueError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            dialogo.close()
            ui.notify("Nó salvo: caminhos recalculados", type="positive")
            await recarregar()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
            ui.button("Salvar", icon="save", on_click=salvar).mark("servidor-salvar")
    dialogo.open()


def _dialogo_remocao(sessao: Sessao, no: ServidorOut, recarregar) -> None:
    with ui.dialog() as dialogo, ui.card():
        ui.label(f"Remover o nó {no.nome}?").classes("text-lg font-bold")
        ui.label(f"Os {len(no.clientes)} cliente(s) dele migram para o nó ligado menos ocupado.").classes("text-sm")

        async def confirmar() -> None:
            try:
                await sessao.api.remover_servidor(no.id)
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            dialogo.close()
            ui.notify(f"Nó {no.nome} removido", type="warning")
            await recarregar()

        with ui.row():
            ui.button("Remover", on_click=confirmar).props("color=negative").mark("servidor-confirmar-remocao")
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
    dialogo.open()
