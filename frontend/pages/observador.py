"""Painel Observador (RF15): o caminho de cada envelope pelos nós, ao vivo, e o que o servidor e um
interceptador enxergam. Só administradores: são os metadados de todos os usuários."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui
from websockets.exceptions import InvalidHandshake

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.observador import ClienteObservador
from frontend.pages import diagrama
from frontend.pages.caminho import legenda
from frontend.pages.layout import cartao, conectar, encurtar, hora, mensagem_erro, moldura, secao, selo_modo, titulo_pagina
from frontend.sessao import Sessao
from shared.crypto import fatoracao
from shared.crypto.chaves import carregar_publica
from shared.crypto.envelope import ErroEnvelope, decifrar_capturado
from shared.schemas import Envelope

ROTULO_STATUS = {"entregue": "entregue", "offline": "na fila (offline)", "sem_rota": "na fila (sem caminho)"}
COR_STATUS = {"entregue": "positive", "offline": "warning", "sem_rota": "warning"}


def registrar_paginas(sessao: Sessao, observador: ClienteObservador, mensageiro: Mensageiro) -> None:
    @ui.page("/observador")
    async def pagina():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        if sessao.admin:
            try:
                await observador.conectar()
                observador.adulteracao_armada = await sessao.api.adulteracao()
            except (ErroApi, httpx.HTTPError, OSError, InvalidHandshake) as erro:
                ui.notify(f"Sem conexão com o canal do observador: {mensagem_erro(erro)}", type="negative")
        with moldura(sessao, mensageiro, "/observador") as conteudo:
            conteudo.classes("max-w-none")
            titulo_pagina(
                "Observador",
                "Todo o tráfego, ao vivo: por onde cada envelope anda e o que o servidor e um espião conseguem ver.",
                "hub",
            )
            if not sessao.admin:
                ui.label("Só administradores acompanham o tráfego de todos os usuários.").classes("text-slate-600")
                return

            estado = {"selecionado": None, "seguir": True}  # selecionado = seq de um evento "transito"

            def evento_atual() -> dict | None:
                transitos = observador.recentes({"transito"})
                if estado["seguir"] or estado["selecionado"] is None:
                    return transitos[0] if transitos else None
                return observador.eventos.get(estado["selecionado"])

            def selecionar(seq: int) -> None:
                estado["selecionado"], estado["seguir"] = seq, False
                seguir.value = False
                redesenhar()

            with ui.row().classes("w-full gap-4 items-stretch no-wrap max-lg:flex-wrap"):
                with cartao("grow min-w-0"):
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.label("Caminho do envelope").classes("text-base font-bold text-slate-800")
                        legenda()
                        ui.space()
                        seguir = ui.switch("acompanhar o mais recente", value=True,
                                           on_change=lambda e: (estado.update(seguir=e.value), redesenhar()))

                        async def alternar_adulteracao() -> None:
                            try:
                                observador.adulteracao_armada = await sessao.api.armar_adulteracao(not observador.adulteracao_armada)
                            except (ErroApi, httpx.HTTPError) as erro:
                                ui.notify(mensagem_erro(erro), type="negative")
                            redesenhar()

                        botao_adulterar = ui.button(on_click=alternar_adulteracao).props("no-caps").mark("observador-adulterar")
                    grafico = ui.echart({"series": []}).classes("w-full").style("height: 470px")
                    resumo = ui.label().classes("text-sm text-slate-700")

                with cartao("w-96 shrink-0 max-lg:w-full"):
                    ui.label("Tráfego ao vivo").classes("text-base font-bold text-slate-800")
                    with ui.scroll_area().style("height: 520px").classes("w-full"):

                        @ui.refreshable
                        def trafego() -> None:
                            eventos = observador.recentes()
                            if not eventos:
                                ui.label("Nada ainda. Envie uma mensagem pelo chat.").classes("text-sm text-slate-500")
                            atual = evento_atual()
                            for evento in eventos[:120]:
                                _linha_evento(evento, atual is not None and evento["seq"] == atual["seq"], selecionar)

                        trafego()

            with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):

                @ui.refreshable
                def visoes() -> None:
                    evento = evento_atual()
                    if evento is None:
                        return
                    _visao_servidor(evento)
                    _visao_interceptador(sessao, evento)

                visoes()

            def redesenhar() -> None:
                armada = observador.adulteracao_armada
                botao_adulterar.text = "Adulteração armada: o próximo envelope será alterado" if armada else "Adulterar o próximo envelope"
                botao_adulterar.props(f"color={'negative' if armada else 'grey-8'} {'unelevated' if armada else 'outline'}")
                botao_adulterar.props(remove="outline" if armada else "unelevated")
                evento = evento_atual()
                seq = evento["seq"] if evento else None
                # cada parte só é refeita quando o que ela mostra muda: refazer as visões a cada evento
                # apagaria o resultado do "quebrar a chave" que o usuário acabou de pedir
                desenho = (seq, observador.topologia.model_dump_json() if observador.topologia else None)
                if observador.topologia is not None and desenho != estado.get("desenho"):
                    estado["desenho"] = desenho
                    if evento is None:
                        grafico.options.update(diagrama.opcoes(observador.topologia))
                        resumo.text = "Aguardando o primeiro envelope…"
                    else:
                        grafico.options.update(diagrama.opcoes(
                            observador.topologia, evento["caminho"], evento["de"], evento["para"],
                            evento["status"], evento.get("adulterado", False),
                        ))
                        resumo.text = _descrever(evento)
                    grafico.update()
                trafego.refresh()
                if seq != estado.get("visao", -1):
                    estado["visao"] = seq
                    visoes.refresh()

            ultima = {"versao": -1}

            def talvez_redesenhar() -> None:
                if observador.versao != ultima["versao"]:
                    ultima["versao"] = observador.versao
                    redesenhar()

            ui.timer(0.4, talvez_redesenhar)
            redesenhar()


def _caminho_texto(evento: dict) -> str:
    if evento["caminho"] is None:
        return "sem caminho entre os nós"
    return " › ".join(evento["caminho"]) if evento["caminho"] else "relay central"


def _descrever(evento: dict) -> str:
    texto = f"@{evento['de']} → {_caminho_texto(evento)} → @{evento['para']} · {evento['blocos']} bloco(s), {evento['bytes']} bytes cifrados"
    if evento.get("adulterado"):
        texto += " · ⚠ um bloco foi alterado pelo servidor: o destinatário vai rejeitar pela assinatura"
    return texto


def _linha_evento(evento: dict, selecionado: bool, selecionar) -> None:
    tipo = evento["type"]
    classes = "w-full rounded-xl p-2 gap-1 no-wrap items-start " + ("bg-teal-50 ring-1 ring-teal-200" if selecionado else "")
    with ui.row().classes(classes) as linha:
        if tipo == "transito":
            linha.classes("cursor-pointer hover:bg-slate-50").on("click", lambda s=evento["seq"]: selecionar(s))
            icone = "gpp_bad" if evento.get("adulterado") else ("lock" if evento["status"] == "entregue" else "schedule")
            cor = "negative" if evento.get("adulterado") else COR_STATUS[evento["status"]]
            ui.icon(icone, color=cor).classes("text-lg mt-0.5")
            with ui.column().classes("gap-0 min-w-0 grow"):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.label(f"@{evento['de']} → @{evento['para']}").classes("font-medium text-sm")
                    selo_modo(evento["modo"])
                ui.label(encurtar(_caminho_texto(evento), 44)).classes("text-xs text-slate-600")
                rotulo = ROTULO_STATUS[evento["status"]] + (" (da fila)" if evento.get("da_fila") else "")
                ui.label(rotulo + (" · adulterado" if evento.get("adulterado") else "")).classes("text-xs text-slate-500")
        else:
            icone, texto = _resumo_evento(evento)
            ui.icon(icone, color="grey-7").classes("text-lg mt-0.5")
            ui.label(texto).classes("text-xs text-slate-600 grow")
        ui.label(hora(evento["ts"]) + evento["ts"][16:19]).classes("text-xs text-slate-400 shrink-0")


def _resumo_evento(evento: dict) -> tuple[str, str]:
    tipo = evento["type"]
    if tipo == "confirmado":
        return "done_all", f"@{evento['por']} confirmou {evento['message_id'][:8]}…"
    if tipo == "recusado":
        return "block", f"recusado de @{evento['de']}: {evento['code']}"
    if tipo == "conexao":
        return ("login", f"@{evento['usuario']} conectou") if evento["online"] else ("logout", f"@{evento['usuario']} desconectou")
    if tipo == "chave":
        return "key", f"@{evento['usuario']} {evento['evento']} a chave {evento['modo']} ({evento['avisados']} contato(s) avisado(s))"
    if tipo == "no":
        return "dns", f"nó {evento['no']} {'ligado' if evento['ativo'] else 'desligado'} por @{evento['por']}"
    if tipo == "cliente_removido":
        return "person_remove", f"@{evento['usuario']} removido por @{evento['por']}"
    if tipo == "adulteracao":
        return "gpp_maybe", f"adulteração {'armada' if evento['ativo'] else 'desarmada'} por @{evento['por']}"
    return "info", json.dumps(evento, ensure_ascii=False)[:80]


def _visao_servidor(evento: dict) -> None:
    envelope = evento["envelope"]
    with secao("Visão do servidor", "dns", "Tudo o que o relay sabe deste envelope — e grava no banco.").classes("grow basis-96"):
        linhas = [
            ("Quem → quem", f"@{evento['de']} → @{evento['para']}"),
            ("Quando", envelope["sent_at"]),
            ("Por onde", _caminho_texto(evento)),
            ("Tamanho", f"{evento['blocos']} bloco(s), {evento['bytes']} bytes cifrados"),
            ("Situação", ROTULO_STATUS[evento["status"]]),
        ]
        for rotulo, valor in linhas:
            with ui.row().classes("gap-2 no-wrap w-full"):
                ui.label(rotulo).classes("text-xs text-slate-500 w-24 shrink-0")
                ui.label(valor).classes("text-sm break-all")
        ui.label("Conteúdo guardado (blocos cifrados, em hexadecimal):").classes("text-xs text-slate-500 mt-2")
        blocos = [base64.b64decode(b).hex() for b in envelope["blocks"][:6]]
        ui.code("\n".join(encurtar(b, 72) for b in blocos) + ("\n…" if len(envelope["blocks"]) > 6 else ""), language=None).classes(
            "w-full text-xs"
        )
        with ui.row().classes("items-center gap-2 no-wrap rounded-xl bg-emerald-50 px-3 py-2"):
            ui.icon("visibility_off", color="positive")
            ui.label("O texto não está aqui: o servidor não tem a privada de ninguém.").classes("text-sm text-emerald-900")


def _visao_interceptador(sessao: Sessao, evento: dict) -> None:
    envelope = Envelope.model_validate(evento["envelope"])
    with secao(
        "Visão do interceptador",
        "wifi_tethering_error",
        "Um espião na rede (ws:// sem TLS) captura o quadro inteiro, metadados inclusive.",
    ).classes("grow basis-96"):
        quadro = json.dumps({"type": "message", "envelope": evento["envelope"]}, ensure_ascii=False)
        ui.code(encurtar(quadro, 280), language="json").classes("w-full text-xs")
        bruto = base64.b64decode(envelope.blocks[0])
        ui.label("Tentando ler o 1º bloco como texto:").classes("text-xs text-slate-500")
        ui.label(bruto.decode("latin-1").translate({i: "·" for i in range(32)})[:64]).classes(
            "font-mono text-sm bg-slate-100 rounded px-2 break-all"
        )
        resultado = ui.column().classes("w-full gap-1")

        if envelope.mode == "didatico":
            async def quebrar_e_ler() -> None:
                resultado.clear()
                try:
                    publica = carregar_publica((await sessao.api.chave_por_id(envelope.to_key_id)).public_key)
                    quebrada = await asyncio.to_thread(fatoracao.quebrar, publica)
                    conteudo = decifrar_capturado(envelope, quebrada.privada())
                except (ErroApi, httpx.HTTPError, fatoracao.FatoracaoFalhou, ErroEnvelope) as erro:
                    with resultado:
                        ui.label(f"Não deu: {mensagem_erro(erro)}").classes("text-sm text-slate-600")
                    return
                f = quebrada.fatoracao
                with resultado:
                    ui.label(
                        f"n = {f.n} = {f.p} × {f.q}  ({f.metodo}, {f.passos} passos, {f.duracao_ms:.1f} ms)"
                    ).classes("font-mono text-xs")
                    ui.label(f"φ(n) = {quebrada.phi}   d = e⁻¹ mod φ(n) = {quebrada.d}").classes("font-mono text-xs")
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("lock_open", color="negative")
                        ui.label(f"Mensagem lida: “{conteudo['text']}”").classes("text-base font-bold text-red-700").mark(
                            "interceptador-texto"
                        )
                    ui.label("Chave didática de poucos bits: fatorar n devolve d. Por isso o modo real usa 2048 bits.").classes(
                        "text-xs text-slate-600"
                    )

            ui.button(f"Quebrar a chave de @{envelope.to} e ler", icon="lock_open", on_click=quebrar_e_ler).props(
                "outline color=negative no-caps"
            ).mark("interceptador-quebrar")
        else:
            with ui.row().classes("items-center gap-2 no-wrap rounded-xl bg-emerald-50 px-3 py-2"):
                ui.icon("verified_user", color="positive")
                ui.label("RSA-OAEP 2048: sem a privada, só fatorando um n de 617 dígitos — inviável.").classes(
                    "text-sm text-emerald-900"
                )
