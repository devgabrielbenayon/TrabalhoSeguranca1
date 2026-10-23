"""Inspetor (RF14): uma mensagem passo a passo neste aparelho — cada etapa do RSA com os valores reais.

A jornada tem três fases: no aparelho de quem envia (texto → bytes → cifra RSA-OAEP → assinatura RSA-PSS),
na rede (os nós) e no aparelho de quem recebe (verificação → decifragem → texto). Cada passo mostra um
resumo; os detalhes (blocos, assinatura) ficam ao abrir o passo. O rastro é local (tem texto claro): não
sai daqui.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Callable

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import inspecao
from frontend.api_client import ErroApi
from frontend.keystore import ChaveNaoEncontrada
from frontend.key_cache import ChaveSuspeita
from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro
from frontend.pages.caminho import trilha_percurso
from frontend.pages.layout import (
    TONS,
    avatar,
    cartao,
    conectar,
    encurtar,
    hora,
    item_mensagem,
    mensagens_com_envelope,
    moldura,
    pilula,
    secao,
    titulo_pagina,
    vazio,
)
from frontend.sessao import Sessao
from shared.crypto import rsa_real
from shared.crypto.chaves import ChavePrivada, ChavePublica
from shared.schemas import Envelope, EventoTransitoOut
from shared.trace import TraceEvent

CONTROLE = {i: "·" for i in (*range(32), *range(127, 160))}  # bytes sem caractere visível em latin-1
ICONE_REDE = {"recebido": "move_to_inbox", "salto": "alt_route", "entregue": "outbox", "fila": "schedule", "confirmado": "done_all"}
NOME_EVENTO = {"recebido": "recebido", "salto": "repassado", "entregue": "entregue", "fila": "na fila", "confirmado": "confirmado"}
# status da mensagem → (texto, tom)
SITUACAO = {
    "verificada": ("assinatura verificada", "ok"),
    "entregue": ("entregue", "ok"),
    "enviada": ("enviada", "neutro"),
    "enviando": ("enviando", "neutro"),
    "rejeitada": ("rejeitada", "erro"),
    "erro": ("não enviada", "erro"),
}


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/inspetor")
    async def pagina(mensagem: str | None = None, para: str | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        itens = mensagens_com_envelope(mensageiro)
        escolhido = next((ci for ci in itens if ci[1].message_id == mensagem), itens[0] if itens else None)
        detalhe = await _carregar(sessao, mensageiro, *escolhido) if escolhido is not None else None

        with moldura(sessao, mensageiro, "/inspetor") as conteudo:
            conteudo.classes("max-w-none")
            titulo_pagina("Inspetor", "Uma mensagem passo a passo: do texto ao cifrado e de volta, com os números reais.", "biotech")
            with ui.row().classes("w-full gap-4 no-wrap items-start max-lg:flex-wrap"):
                with cartao("w-80 shrink-0 max-lg:w-full gap-1 p-3"):
                    ui.label("Mensagens").classes("text-base font-bold text-stone-800 px-1")
                    if not itens:
                        ui.label("Nenhuma mensagem ainda.").classes("text-sm text-stone-500 px-1")
                    with ui.scroll_area().style("height: calc(100vh - 250px)").classes("w-full"):
                        for conversa, item in itens:
                            item_mensagem(
                                conversa, item, escolhido is not None and item is escolhido[1],
                                lambda m=item.message_id: ui.navigate.to(f"/inspetor?mensagem={m}"),
                            )
                with ui.column().classes("grow gap-4 min-w-0"):
                    if detalhe is None:
                        with cartao("w-full"):
                            vazio("biotech", "Envie uma mensagem pelo chat e volte aqui para ver cada passo da criptografia.")
                    else:
                        _mostrar_detalhe(detalhe, mensageiro.eu, para)


# ---------------------------------------------------------------- dados de uma mensagem


@dataclass
class Detalhe:
    conversa: ConversaLocal
    item: ItemMensagem
    envio: list[TraceEvent]
    recebimento: list[TraceEvent]
    rede: list[EventoTransitoOut]
    para_mim: Envelope | None
    privada: ChavePrivada | None
    publica_remetente: ChavePublica | None


async def _carregar(sessao: Sessao, mensageiro: Mensageiro, conversa: ConversaLocal, item: ItemMensagem) -> Detalhe:
    eventos = inspecao.eventos_da_mensagem(sessao.tracer, item.message_id)
    envio = [e for e in eventos if e.etapa in inspecao.ETAPAS_ENVIO]
    recebimento = [e for e in eventos if e.etapa in inspecao.ETAPAS_RECEBIMENTO]
    para_mim = next((e for e in item.envelopes if e.to == mensageiro.eu), None)

    # sem rastro do recebimento (veio do histórico, ou é a cópia de algo enviado agora): refaz com o envelope
    privada = publica_remetente = None
    if para_mim is not None:
        try:
            privada = sessao.keystore.carregar(para_mim.to_key_id)
            publica_remetente = await mensageiro.cache.por_id(para_mim.from_, para_mim.from_key_id)
        except (ChaveNaoEncontrada, ChaveSuspeita, ErroApi, httpx.HTTPError):
            privada = None
        if privada is not None and not recebimento:
            recebimento = inspecao.refazer_recebimento(para_mim, privada, publica_remetente)
    try:
        rede = await sessao.api.rastro(item.message_id)
    except (ErroApi, httpx.HTTPError):
        rede = []
    return Detalhe(conversa, item, envio, recebimento, rede, para_mim, privada, publica_remetente)


def _primeiro(eventos: list[TraceEvent], etapa: str, para: str | None = None) -> TraceEvent | None:
    for e in eventos:
        if e.etapa == etapa and (para is None or (isinstance(e.entrada, dict) and e.entrada.get("para") == para)):
            return e
    return None


# ---------------------------------------------------------------- tela de uma mensagem


def _mostrar_detalhe(d: Detalhe, eu: str, para: str | None) -> None:
    alvos = [p for p in d.conversa.participantes if p != d.item.remetente] or [eu]
    estado = {"alvo": para if para in alvos else (eu if eu in alvos else alvos[0])}
    _cabecalho(d)

    @ui.refreshable
    def corpo() -> None:
        alvo = estado["alvo"]
        envelope = next((e for e in d.item.envelopes if e.to == alvo), d.para_mim or d.item.envelopes[0])
        _quem_ve(d.item, envelope)
        if len(alvos) > 1 and d.item.propria:
            with ui.row().classes("items-center gap-2"):
                ui.label("Um envelope por destinatário. Ver o de:").classes("text-sm text-stone-600")
                ui.toggle({p: f"@{p}" for p in alvos}, value=alvo, on_change=lambda e: (estado.update(alvo=e.value), corpo.refresh())).props(
                    "dense no-caps unelevated toggle-color=primary"
                )
        _jornada(d, alvo, eu)

    corpo()
    if d.para_mim is not None and d.privada is not None:
        _experimentos(d.para_mim, d.publica_remetente, d.item.propria)


def _cabecalho(d: Detalhe) -> None:
    item = d.item
    destinos = [p for p in d.conversa.participantes if p != item.remetente]
    with cartao("w-full p-5 gap-3"):
        with ui.row().classes("items-center gap-2 w-full"):
            if item.propria:
                pilula("enviada por você", "info", "north_east")
            else:
                pilula(f"recebida de @{item.remetente}", "info", "south_west")
            texto, tom = SITUACAO.get(item.status, (item.status, "neutro"))
            pilula(texto, tom)
            ui.space()
            ui.label(hora(item.sent_at)).classes("text-xs text-stone-400")
            ui.button("Ver o caminho", icon="route", on_click=lambda: ui.navigate.to(f"/caminho?mensagem={item.message_id}")).props(
                "flat dense no-caps color=primary"
            )
        ui.label(f"“{item.texto}”" if item.texto is not None else "[não foi possível ler esta mensagem]").classes(
            "text-xl text-stone-800 break-words " + ("" if item.texto is not None else "txt-erro italic")
        )
        with ui.row().classes("items-center gap-2"):
            avatar(item.remetente, tamanho=7)
            ui.label(f"@{item.remetente}").classes("text-sm font-medium")
            ui.icon("arrow_forward", color="grey-6")
            for p in destinos:
                avatar(p, tamanho=7)
                ui.label(f"@{p}").classes("text-sm font-medium")
        if item.erro:
            ui.label(item.erro).classes("text-sm txt-erro")


def _quem_ve(item: ItemMensagem, envelope: Envelope) -> None:
    """A mesma mensagem sob três olhares: o aparelho, o servidor e alguém escutando a rede."""
    bruto = base64.b64decode(envelope.blocks[0])[:24]
    with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
        with _olhar("Você", "smartphone", "ok", "lê o texto: tem a chave privada"):
            ui.label(item.texto if item.texto is not None else "[não foi possível decifrar]").classes(
                "text-base font-semibold break-words " + ("txt-ok" if item.texto else "txt-erro")
            )
        with _olhar("O servidor", "dns", "neutro", "sabe quem fala com quem, mas não lê"):
            ui.label(f"@{envelope.from_} → @{envelope.to} · {len(envelope.blocks)} bloco(s)").classes("text-sm")
            ui.label(encurtar(bruto.hex(), 44)).classes("font-mono text-xs text-stone-500 break-all")
        with _olhar("Um espião na rede", "wifi_tethering_error", "erro", "só vê bytes embaralhados"):
            ui.label(bruto.decode("latin-1").translate(CONTROLE)).classes(
                "font-mono text-sm text-stone-600 break-all"
            )


def _olhar(titulo: str, icone: str, tom: str, legenda: str) -> ui.column:
    with cartao("grow basis-56 p-4 gap-2"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            with ui.element("div").classes(f"rounded-lg p-1 flex ring-1 {TONS[tom]}"):
                ui.icon(icone).classes("text-base")
            ui.label(titulo).classes("text-sm font-bold text-stone-800")
        corpo = ui.column().classes("gap-1 w-full")
        ui.label(legenda).classes("text-xs text-stone-500 mt-auto")
    return corpo


# ---------------------------------------------------------------- a jornada em 7 passos


def _jornada(d: Detalhe, alvo: str, eu: str) -> None:
    item = d.item
    remetente = item.remetente

    with _fase(f"No aparelho de @{remetente}" + (" (você)" if item.propria else ""), "smartphone", "Cifrar e assinar"):
        _passos_envio(d, alvo)
    _seta()
    with _fase("Na rede", "hub", "O servidor só repassa"):
        _passo_rede(d, alvo)
    _seta()
    with _fase(f"No aparelho de @{alvo}" + (" (você)" if alvo == eu else ""), "smartphone", "Conferir e decifrar"):
        if item.propria:
            _recebimento_remoto(d, alvo)
        else:
            _passos_recebimento(d.recebimento, remetente, alvo)


def _passos_envio(d: Detalhe, alvo: str) -> None:
    remetente = d.item.remetente
    cod = _primeiro(d.envio, "codificacao")
    cif = _primeiro(d.envio, "cifragem", alvo)
    ass = _primeiro(d.envio, "assinatura", alvo)
    if not (cod or cif or ass):
        envelope = next((e for e in d.item.envelopes if e.to == alvo), d.para_mim)
        if d.item.propria:
            _nota("Enviada antes desta sessão: os cálculos do envio não ficaram guardados neste aparelho.")
        elif envelope is not None:
            _nota(
                f"Estes cálculos aconteceram no aparelho de @{remetente}: ele cifrou com a sua chave pública "
                f"({envelope.to_key_id}) e assinou com a privada dele ({envelope.from_key_id}). "
                f"Chegaram aqui {len(envelope.blocks)} bloco(s) cifrado(s)."
            )
        return
    if cod:
        _passo(
            1, "text_fields", "Texto vira bytes",
            "O texto, junto com o remetente e o id da mensagem, é codificado em UTF-8.",
            f"{cod.detalhes.get('bytes')} bytes", lambda: _detalhe_codificacao(cod), cod.duracao_ms,
        )
    if cif:
        _passo(
            2, "lock", f"Cifrar com a chave pública de @{alvo}",
            f"Cada pedaço da mensagem é cifrado: só a privada de @{alvo} desfaz.",
            f"{len(cif.detalhes.get('blocos', []))} bloco(s) RSA-OAEP", lambda: _detalhe_cifragem(cif), cif.duracao_ms,
        )
    if ass:
        _passo(
            3, "draw", f"Assinar com a chave privada de @{remetente}",
            "Prova que veio de quem diz ter enviado e que nada foi alterado no caminho.",
            "RSA-PSS · SHA-256", lambda: _detalhe_assinatura(ass), ass.duracao_ms,
        )


def _passo_rede(d: Detalhe, alvo: str) -> None:
    if not d.rede:
        _passo(4, "hub", "Atravessa a rede", "O servidor não registrou o trânsito desta mensagem.", "sem registro")
        return
    p = inspecao.percurso(d.rede, alvo)
    if p.status == "sem_rota":
        valor, tom = f"parada em {p.parado_em}: sem caminho", "alerta"
    else:
        valor, tom = (" › ".join(p.nos) if p.nos else "relay central"), ("alerta" if p.status == "offline" else "neutro")
    _passo(
        4, "hub", "Atravessa os nós da rede",
        "Cada nó só repassa o envelope cifrado: nenhum deles tem chave privada.",
        valor, lambda: _detalhe_rede(d, p), tom_valor=tom,
    )


def _recebimento_remoto(d: Detalhe, alvo: str) -> None:
    """Mensagem enviada daqui: quem decifra é o aparelho do destinatário, com a privada que só ele tem."""
    p = inspecao.percurso(d.rede, alvo)
    if p.confirmado:
        situacao, tom = f"@{alvo} recebeu e confirmou", "ok"
    elif p.status == "entregue":
        situacao, tom = f"entregue a @{alvo}", "ok"
    elif p.status in ("offline", "sem_rota"):
        situacao, tom = "esperando na fila", "alerta"
    else:
        situacao, tom = "a caminho", "info"
    with ui.row().classes("items-center gap-3 w-full px-3 py-2"):
        pilula(situacao, tom, "mark_email_read" if tom == "ok" else "schedule")
        ui.label(
            f"@{alvo} confere a assinatura com a sua chave pública e decifra com a privada dele (passos 5 a 7). "
            f"Só o aparelho de @{alvo} consegue: abra o Inspetor lá para ver."
        ).classes("text-sm text-stone-600 grow basis-64")
    if d.recebimento:
        with ui.expansion("Ver os passos 5 a 7 com a sua cópia", icon="content_copy").classes("w-full text-sm text-stone-600"):
            _nota("Você também recebe uma cópia cifrada com a SUA chave pública: o processo é o mesmo.")
            _passos_recebimento(d.recebimento, d.item.remetente, d.item.remetente)


def _passos_recebimento(recebimento: list[TraceEvent], remetente: str, alvo: str) -> None:
    if not recebimento:
        _nota("Não foi possível refazer: a chave privada desta mensagem não está neste aparelho.")
        return
    ver = _primeiro(recebimento, "verificacao")
    if ver:
        _passo(
            5, "verified", f"Conferir a assinatura com a chave pública de @{remetente}",
            "Se um único bit mudasse no caminho, a conta não bateria e a mensagem seria descartada.",
            "✓ confere" if ver.saida else "✗ não confere", lambda: _detalhe_verificacao(ver), ver.duracao_ms,
            tom_valor="ok" if ver.saida else "erro",
        )
    dec = _primeiro(recebimento, "decifragem")
    if dec:
        _passo(
            6, "lock_open", f"Decifrar com a chave privada de @{alvo}",
            "A privada nunca saiu deste aparelho: é a única que desfaz a cifra.",
            f"{len(dec.detalhes.get('blocos', []))} bloco(s) RSA-OAEP", lambda: _detalhe_decifragem(dec), dec.duracao_ms,
        )
    txt = _primeiro(recebimento, "decodificacao")
    if txt:
        _passo(
            7, "chat", "Bytes voltam a ser texto",
            "O remetente e o id escondidos dentro da cifra são conferidos com o envelope.",
            f"“{encurtar(str(txt.saida), 40)}”" if txt.saida else "ilegível", lambda: _detalhe_decodificacao(txt), txt.duracao_ms,
            tom_valor="ok" if txt.saida else "erro",
        )


def _fase(titulo: str, icone: str, subtitulo: str) -> ui.column:
    with cartao("w-full p-0 gap-0 overflow-hidden"):
        with ui.row().classes("w-full items-center gap-2 no-wrap px-4 py-2 bg-stone-50 border-b border-stone-200"):
            ui.icon(icone, color="primary").classes("text-lg")
            ui.label(titulo).classes("font-bold text-stone-800")
            ui.label(subtitulo).classes("rotulo ml-auto")
        corpo = ui.column().classes("w-full gap-0 p-2")
    return corpo


def _seta() -> None:
    ui.icon("south").classes("self-center text-2xl text-stone-300 -my-3")


def _nota(texto: str) -> None:
    with ui.row().classes("items-start gap-2 no-wrap px-3 py-2"):
        ui.icon("info", color="grey-6").classes("text-base mt-0.5")
        ui.label(texto).classes("text-sm text-stone-600")


def _passo(
    numero: int,
    icone: str,
    titulo: str,
    explicacao: str,
    valor: str,
    detalhes: Callable[[], None] | None = None,
    ms: float | None = None,
    tom_valor: str = "neutro",
) -> None:
    """Um passo: resumo sempre visível; os números completos aparecem ao abrir."""
    passo = ui.expansion().classes("w-full passo")
    with passo.add_slot("header"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.label(str(numero)).classes(
                "rounded-full bolinha w-7 h-7 flex items-center justify-center text-sm font-bold shrink-0"
            )
            ui.icon(icone, color="primary").classes("text-xl shrink-0")
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(titulo).classes("font-semibold text-stone-800")
                ui.label(explicacao).classes("text-xs text-stone-500")
            quebra = "break-words" if len(valor) > 24 else "whitespace-nowrap shrink-0"
            ui.label(valor).classes(f"font-mono text-xs rounded-lg px-2 py-1 ring-1 {quebra} {TONS[tom_valor]}").style(
                "max-width: 42%"
            )
            if ms is not None:
                ui.label(f"{ms:.1f} ms").classes("text-[11px] text-stone-400 w-14 text-right shrink-0")
    with passo:
        if detalhes is not None:
            with ui.column().classes("w-full gap-2 pl-12 pr-2 pb-3"):
                detalhes()
    if detalhes is None:
        passo.props("hide-expand-icon")


# ---------------------------------------------------------------- detalhes de cada passo


def _detalhe_codificacao(cod: TraceEvent) -> None:
    ui.label("Conteúdo cifrado (o cabeçalho vai junto, protegido pela cifra):").classes("text-xs text-stone-500")
    ui.code(cod.detalhes.get("conteudo", ""), language="json").classes("w-full text-xs")
    ui.label(f"{cod.detalhes.get('bytes')} bytes em hexadecimal: {encurtar(str(cod.saida), 120)}").classes(
        "font-mono text-xs break-all text-stone-600"
    )


def _detalhe_cifragem(cif: TraceEvent) -> None:
    d = cif.detalhes
    blocos = d.get("blocos", [])
    _formula(f"RSA-OAEP com SHA-256 · e = {d.get('e')} · n de {d.get('bits_n')} bits · até {d.get('tamanho_bloco')} bytes por bloco")
    _tabela(
        ["#", "bloco (hex)", "cifrado (início)"],
        [[i + 1, encurtar(b["bloco_hex"], 40), encurtar(hex(b["c"])[2:], 40)] for i, b in enumerate(blocos)],
    )
    ui.label("O OAEP mistura bytes aleatórios: o mesmo texto cifrado duas vezes dá resultados diferentes.").classes(
        "text-xs text-stone-500"
    )


def _detalhe_assinatura(ass: TraceEvent) -> None:
    d = ass.detalhes
    _formula(f"RSA-PSS com SHA-256 (n de {d.get('bits_n')} bits)")
    ui.label(f"assinatura: {encurtar(str(ass.saida), 64)}").classes("font-mono text-xs break-all text-stone-600")
    with ui.expansion("O que é assinado", icon="data_object").classes("w-full text-sm"):
        ui.label("Todos os campos do envelope menos a assinatura, em JSON canônico:").classes("text-xs text-stone-500")
        ui.code(encurtar(d.get("dados_assinados", ""), 600), language="json").classes("w-full text-xs")


def _detalhe_rede(d: Detalhe, p: inspecao.Percurso) -> None:
    trilha_percurso(d.item.remetente, p)
    with ui.column().classes("w-full gap-0 mt-2"):
        ui.label("Registro do servidor").classes("rotulo pb-1")
        for r in d.rede:
            entrada = r.entrada if isinstance(r.entrada, dict) else {}
            destino = entrada.get("para")
            if isinstance(destino, str) and destino != p.para:
                continue  # eventos do envelope de outro destinatário
            with ui.row().classes("items-center gap-2 no-wrap text-sm py-0.5"):
                ui.label(r.ts.strftime("%H:%M:%S")).classes("font-mono text-xs text-stone-400")
                ui.icon(ICONE_REDE.get(r.etapa, "circle"), color="warning" if r.etapa == "fila" else "grey-7").classes("text-base")
                ui.label(f"{NOME_EVENTO.get(r.etapa, r.etapa)} em {r.ator}").classes("text-stone-700")
    ui.button(
        "Ver no mapa", icon="route", on_click=lambda: ui.navigate.to(f"/caminho?mensagem={d.item.message_id}&para={p.para}")
    ).props("flat dense no-caps color=primary")


def _detalhe_verificacao(ver: TraceEvent) -> None:
    d = ver.detalhes
    _formula(f"RSA-PSS SHA-256 com a pública do remetente (n de {d.get('bits_n')} bits): " + ("válida" if ver.saida else "inválida"))
    if "erro" in d:
        ui.label(d["erro"]).classes("text-sm txt-erro")


def _detalhe_decifragem(dec: TraceEvent) -> None:
    d = dec.detalhes
    blocos = d.get("blocos", [])
    _formula(f"RSA-OAEP: cada bloco de {d.get('bits_n', 2048) // 8} bytes volta ao bloco original")
    _tabela(["#", "bloco decifrado (hex)"], [[i + 1, encurtar(b["bloco_hex"], 60)] for i, b in enumerate(blocos)])
    if "erro" in d:
        ui.label(d["erro"]).classes("text-sm txt-erro")


def _detalhe_decodificacao(txt: TraceEvent) -> None:
    ui.label(f"texto: “{txt.saida}”" if txt.saida else txt.detalhes.get("erro", "")).classes("text-sm")
    ui.label("from e message_id internos conferidos com o envelope externo: ninguém consegue reassinar como se fosse outro.").classes(
        "text-xs text-stone-500"
    )


# ---------------------------------------------------------------- experimentos


def _experimentos(envelope: Envelope, publica_remetente, propria: bool) -> None:
    with secao(
        "E se…?",
        "science",
        "Simulações com o envelope " + ("da sua cópia" if propria else "que chegou") + ", só neste aparelho: nada é enviado.",
    ):

        async def chave_errada() -> None:
            resultado.clear()
            with resultado:
                ui.spinner()
            outra = await asyncio.to_thread(rsa_real.gerar)
            _mostrar(resultado, inspecao.decifrar_com_outra_chave(envelope, outra), "key_off")

        def adulterar() -> None:
            _mostrar(resultado, inspecao.adulterar_e_verificar(envelope, publica_remetente), "gpp_bad")

        with ui.row().classes("gap-2"):
            ui.button("…alguém tentar decifrar com outra chave?", icon="key_off", on_click=chave_errada).props(
                "outline no-caps"
            ).mark("experimento-chave-errada")
            ui.button("…um bit mudar no caminho?", icon="gpp_bad", on_click=adulterar).props("outline no-caps").mark(
                "experimento-adulterar"
            )
        resultado = ui.column().classes("w-full gap-2")


def _mostrar(resultado: ui.column, experimento: inspecao.Experimento, icone: str) -> None:
    resultado.clear()
    with resultado:
        with ui.row().classes("items-start gap-2 no-wrap rounded-xl fundo-rosa px-3 py-2 w-full"):
            ui.icon(icone, color="negative").classes("text-xl mt-0.5")
            with ui.column().classes("gap-0"):
                ui.label(experimento.titulo).classes("font-bold text-sm txt-erro")
                ui.label(experimento.conclusao).classes("text-sm txt-erro").mark("experimento-conclusao")
        if experimento.texto_obtido is not None:
            ui.label(f"Texto obtido: “{encurtar(experimento.texto_obtido, 120)}”").classes("font-mono text-sm txt-erro break-all")
        if experimento.linhas:
            with ui.expansion("Ver os números", icon="table_chart").classes("w-full text-sm"):
                colunas = list(experimento.linhas[0])
                _tabela(colunas, [[_formatar(linha[c]) for c in colunas] for linha in experimento.linhas[:40]])


# ---------------------------------------------------------------- componentes


def _formula(texto: str) -> None:
    ui.label(texto).classes("font-mono text-sm text-stone-800 bg-stone-50 rounded-lg px-3 py-2 break-all w-full")


def _tabela(colunas: list[str], linhas: list[list]) -> None:
    ui.table(
        columns=[{"name": str(i), "label": c, "field": str(i), "align": "left"} for i, c in enumerate(colunas)],
        rows=[{str(i): _formatar(v) for i, v in enumerate(linha)} for linha in linhas],
        pagination={"rowsPerPage": 8},
    ).props("dense flat bordered").classes("w-full text-xs font-mono")


def _formatar(valor) -> str:
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return str(valor)

