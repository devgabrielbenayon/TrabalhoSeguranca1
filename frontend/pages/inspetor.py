"""Inspetor (RF14): o raio-X de uma mensagem neste aparelho — cada etapa do RSA com os números reais.

Envio: texto → bytes UTF-8 → blocos → m → mᵉ mod n → c → assinatura. Rede: os saltos pelos nós.
Recebimento: verificação → cᵈ mod n → bytes → texto. O rastro é local (tem texto claro e d): não sai daqui.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import inspecao
from frontend.api_client import ErroApi
from frontend.keystore import ChaveNaoEncontrada
from frontend.key_cache import ChaveSuspeita
from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro
from frontend.pages.layout import conectar, encurtar, hora, moldura, secao, selo_modo, titulo_pagina
from frontend.sessao import Sessao
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.chaves import ChavePrivada, ChavePublica
from shared.schemas import Envelope, EventoTransitoOut
from shared.trace import TraceEvent

MAX_TABELAS_SM = 3  # tabelas square-and-multiply por etapa (os demais blocos repetem a mesma conta)
NOME_ETAPA = {
    "codificacao": "Codificação",
    "cifragem": "Cifragem",
    "assinatura": "Assinatura",
    "verificacao": "Verificação",
    "decifragem": "Decifragem",
    "decodificacao": "Decodificação",
}
ICONE_ETAPA = {
    "codificacao": "text_fields", "cifragem": "lock", "assinatura": "draw", "verificacao": "verified",
    "decifragem": "lock_open", "decodificacao": "chat",
}


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/inspetor")
    async def pagina(mensagem: str | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        itens = sorted(
            ((c, i) for c in mensageiro.conversas.values() for i in c.mensagens.values() if i.envelopes),
            key=lambda ci: ci[1].sent_at,
            reverse=True,
        )
        escolhido = next((ci for ci in itens if ci[1].message_id == mensagem), itens[0] if itens else None)
        detalhe = await _carregar(sessao, mensageiro, *escolhido) if escolhido is not None else None

        with moldura(sessao, mensageiro, "/inspetor") as conteudo:
            conteudo.classes("max-w-none")
            titulo_pagina(
                "Inspetor",
                "O raio-X de uma mensagem: cada etapa do RSA com os números reais. O rastro fica só neste aparelho.",
                "biotech",
            )
            with ui.row().classes("w-full gap-4 no-wrap items-start max-lg:flex-wrap"):
                with ui.card().classes("w-80 shrink-0 shadow-sm max-lg:w-full"):
                    ui.label("Mensagens").classes("text-lg font-bold")
                    if not itens:
                        ui.label("Nenhuma mensagem ainda. Envie uma pelo chat e volte aqui.").classes("text-sm text-slate-500")
                    with ui.scroll_area().style("height: calc(100vh - 230px)").classes("w-full"):
                        for conversa, item in itens:
                            _item_lista(mensageiro, conversa, item, escolhido is not None and item is escolhido[1])
                with ui.column().classes("grow gap-4 min-w-0"):
                    if detalhe is not None:
                        _mostrar_detalhe(detalhe, mensageiro.eu)


def _item_lista(mensageiro: Mensageiro, conversa: ConversaLocal, item: ItemMensagem, selecionado: bool) -> None:
    destino = ", ".join(p for p in conversa.participantes if p != item.remetente)
    classes = "w-full rounded p-2 gap-2 no-wrap cursor-pointer " + ("bg-teal-50 ring-1 ring-teal-300" if selecionado else "hover:bg-slate-50")
    with ui.row().classes(classes).on("click", lambda: ui.navigate.to(f"/inspetor?mensagem={item.message_id}")):
        ui.icon("call_made" if item.propria else "call_received", color="primary" if item.propria else "info").classes("mt-1")
        with ui.column().classes("gap-0 min-w-0 grow"):
            ui.label(("você" if item.propria else f"@{item.remetente}") + f" → {destino}").classes("text-sm font-medium truncate")
            ui.label(encurtar(item.texto if item.texto is not None else "[descartada]", 40)).classes("text-xs text-slate-600")
            with ui.row().classes("gap-1 items-center"):
                selo_modo(conversa.modo)
                ui.label(hora(item.sent_at)).classes("text-xs text-slate-400")


# ---------------------------------------------------------------- detalhe de uma mensagem


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


def _mostrar_detalhe(d: Detalhe, eu: str) -> None:
    _cabecalho(d.conversa, d.item, eu)
    _trilha(d.item, d.envio, d.recebimento, d.rede, eu)
    _visao_dividida(d.item, d.para_mim or d.item.envelopes[0])
    if d.envio:
        _etapas_envio(d.envio, eu)
    _rede(d.rede)
    if d.recebimento:
        rotulo = "Recebimento (neste aparelho)" if not d.item.propria else "Recebimento da sua cópia (o destinatário faz o mesmo no aparelho dele)"
        _etapas_recebimento(d.recebimento, rotulo)
    _linha_do_tempo(d.envio + d.recebimento)
    if d.para_mim is not None and d.privada is not None:
        _experimentos(d.para_mim, d.privada, d.publica_remetente)


def _cabecalho(conversa: ConversaLocal, item: ItemMensagem, eu: str) -> None:
    with ui.card().classes("w-full shadow-sm"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.icon("call_made" if item.propria else "call_received", color="primary").classes("text-3xl")
            with ui.column().classes("gap-0 grow min-w-0"):
                destino = ", ".join(p for p in conversa.participantes if p != item.remetente)
                ui.label(f"{'Você' if item.propria else '@' + item.remetente} → {destino}").classes("text-lg font-bold")
                ui.label(f"message_id {item.message_id} · enviada {item.sent_at} · assinada com {item.key_id}").classes(
                    "text-xs text-slate-500 font-mono break-all"
                )
            selo_modo(conversa.modo)
            ui.badge(item.status, color="positive" if item.status in ("verificada", "entregue", "enviada") else "negative")
        if item.texto is not None:
            ui.label(f"“{item.texto}”").classes("text-base italic text-slate-800")
        if item.erro:
            ui.label(item.erro).classes("text-sm text-red-700")


def _primeiro(eventos: list[TraceEvent], etapa: str, para: str | None = None) -> TraceEvent | None:
    for e in eventos:
        if e.etapa == etapa and (para is None or (isinstance(e.entrada, dict) and e.entrada.get("para") == para)):
            return e
    return None


def _trilha(item: ItemMensagem, envio: list[TraceEvent], recebimento: list[TraceEvent], rede: list, eu: str) -> None:
    """A trilha de cartões do plano (seção 10): um valor real em cada etapa."""
    alvo = next((e.to for e in item.envelopes if e.to != item.remetente), None)
    cod = _primeiro(envio, "codificacao")
    cif = _primeiro(envio, "cifragem", alvo)
    ass = _primeiro(envio, "assinatura", alvo)
    ver = _primeiro(recebimento, "verificacao")
    dec = _primeiro(recebimento, "decifragem")
    txt = _primeiro(recebimento, "decodificacao")

    cartoes: list[tuple[str, str, str]] = []
    if cod:
        cartoes += [
            ("Texto", "text_fields", encurtar(str(cod.entrada), 30)),
            ("Bytes UTF-8", "data_object", f"{cod.detalhes.get('bytes')} bytes (com cabeçalho interno)"),
        ]
    if cif:
        blocos = cif.detalhes.get("blocos", [])
        cartoes.append(("Blocos", "view_module", f"{len(blocos)} × até {cif.detalhes.get('tamanho_bloco')} bytes"))
        if cif.detalhes.get("modo") == "didatico" and blocos:
            b = blocos[0]
            cartoes += [
                ("Inteiro m", "pin", f"m₁ = {b['m']}"),
                ("mᵉ mod n", "functions", f"{b['m']}^{cif.detalhes['e']} mod {cif.detalhes['n']}"),
                ("c", "lock", f"c₁ = {b['c']}"),
            ]
        else:
            cartoes.append(("RSA-OAEP", "lock", f"cada bloco → {_bytes_b64(cif.saida[0]) if cif.saida else '?'} bytes"))
    if ass:
        if "h" in ass.detalhes:
            cartoes.append(("Assinatura", "draw", f"s = {ass.detalhes['h']}^d mod n"))
        else:
            cartoes.append(("Assinatura", "draw", "RSA-PSS SHA-256"))
    saltos = [r.ator for r in rede if r.etapa == "salto" and (not alvo or r.entrada.get("para") == alvo)]
    if rede:
        cartoes.append(("Rede", "hub", " › ".join(dict.fromkeys(saltos)) if saltos else "relay central"))
    if ver:
        cartoes.append(("Verificação", "verified", "✓ confere" if ver.saida else "✗ não confere"))
    if dec:
        blocos = dec.detalhes.get("blocos", [])
        if "d" in dec.detalhes and blocos:
            cartoes.append(("cᵈ mod n", "lock_open", f"{blocos[0]['c']}^d mod {dec.detalhes['n']} = {blocos[0]['m']}"))
        else:
            cartoes.append(("Decifragem", "lock_open", f"{len(blocos)} bloco(s) OAEP"))
    if txt:
        cartoes.append(("Texto", "chat", encurtar(str(txt.saida), 30)))

    with secao("Raio-X", "biotech", "Cada cartão é uma etapa, com o valor real desta mensagem (detalhes abaixo)."):
        with ui.row().classes("w-full gap-1 items-stretch flex-wrap"):
            for i, (titulo, icone, valor) in enumerate(cartoes):
                with ui.card().classes("w-40 bg-slate-50 shadow-none border border-slate-200 p-2 gap-1"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.icon(icone, color="primary").classes("text-base")
                        ui.label(titulo).classes("text-xs font-bold text-slate-700")
                    ui.label(valor).classes("text-xs font-mono break-all text-slate-800")
                if i < len(cartoes) - 1:
                    ui.icon("arrow_forward", color="grey-6").classes("self-center")


def _visao_dividida(item: ItemMensagem, envelope: Envelope) -> None:
    """A mesma mensagem sob três perspectivas."""
    with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
        with secao("Neste aparelho", "smartphone").classes("grow basis-64"):
            ui.label(item.texto if item.texto is not None else "[não foi possível decifrar]").classes(
                "text-base " + ("text-green-800 font-bold" if item.texto else "text-red-700")
            )
            ui.label(f"decifrado com a privada {envelope.to_key_id}, que só existe aqui").classes("text-xs text-slate-500")
        with secao("No servidor", "dns").classes("grow basis-64"):
            ui.label(f"de @{envelope.from_} para @{envelope.to} · {len(envelope.blocks)} bloco(s)").classes("text-sm")
            ui.label(encurtar(base64.b64decode(envelope.blocks[0]).hex(), 60)).classes("font-mono text-xs break-all text-slate-700")
            ui.label("vê quem fala com quem e quando, mas não o texto").classes("text-xs text-slate-500")
        with secao("Na rede", "wifi_tethering_error").classes("grow basis-64"):
            ui.label(base64.b64decode(envelope.blocks[0]).decode("latin-1").translate({i: "·" for i in range(32)})[:48]).classes(
                "font-mono text-sm break-all text-slate-700"
            )
            ui.label("um interceptador captura bytes sem sentido (e os metadados)").classes("text-xs text-slate-500")


def _etapas_envio(envio: list[TraceEvent], eu: str) -> None:
    with secao("Envio (neste aparelho)", "outbox", "Um envelope por destinatário, mais a cópia para você. Cada um cifrado com a pública de quem vai ler e assinado com a sua privada."):
        cod = _primeiro(envio, "codificacao")
        if cod:
            with ui.expansion("Codificação: texto → JSON com cabeçalho interno → bytes UTF-8", icon="text_fields").classes("w-full"):
                ui.code(cod.detalhes.get("conteudo", ""), language="json").classes("w-full text-xs")
                ui.label(f"{cod.detalhes.get('bytes')} bytes: {encurtar(str(cod.saida), 160)}").classes("font-mono text-xs break-all")
                ui.label("O cabeçalho (from, message_id) vai cifrado: o destinatário confere com o envelope externo.").classes(
                    "text-xs text-slate-500"
                )
        for cif in (e for e in envio if e.etapa == "cifragem"):
            para = cif.entrada.get("para")
            titulo = f"Cifragem para @{para}" + (" (sua cópia)" if para == eu else "") + f" — chave {cif.entrada.get('key_id')}"
            with ui.expansion(titulo, icon="lock").classes("w-full"):
                _detalhe_cifragem(cif)
        for ass in (e for e in envio if e.etapa == "assinatura"):
            para = ass.entrada.get("para")
            with ui.expansion(f"Assinatura do envelope de @{para}" + (" (sua cópia)" if para == eu else ""), icon="draw").classes("w-full"):
                _detalhe_assinatura(ass)


def _detalhe_cifragem(cif: TraceEvent) -> None:
    d = cif.detalhes
    blocos = d.get("blocos", [])
    if d.get("modo") == "didatico":
        ui.label(f"c = mᵉ mod n   com e = {d['e']} e n = {d['n']} · blocos de {d['tamanho_bloco']} byte(s), completados com zeros").classes(
            "font-mono text-sm"
        )
        _tabela(
            ["#", "bloco (hex)", "m", "c = mᵉ mod n"],
            [[i + 1, b["bloco_hex"], b["m"], b["c"]] for i, b in enumerate(blocos)],
        )
        _repeticoes(blocos)
        for i, b in enumerate(blocos[:MAX_TABELAS_SM]):
            _square_and_multiply(f"Bloco {i + 1}: {b['m']}^{d['e']} mod {d['n']} = {b['c']}", b.get("passos") or [], d["e"])
    else:
        ui.label(
            f"RSA-OAEP com SHA-256 · e = {d.get('e')}, n de {d.get('bits_n')} bits · até {d.get('tamanho_bloco')} bytes por bloco"
        ).classes("text-sm")
        _tabela(
            ["#", "bloco (hex)", "cifrado (início)"],
            [[i + 1, encurtar(b["bloco_hex"], 40), encurtar(hex(b["c"])[2:], 40)] for i, b in enumerate(blocos)],
        )
        ui.label("O OAEP é aleatorizado: o mesmo bloco cifrado duas vezes dá resultados diferentes.").classes("text-xs text-slate-500")


def _repeticoes(blocos: list[dict]) -> None:
    """RSA de livro é determinístico: blocos iguais viram cifrados iguais (o Inspetor avisa)."""
    vistos: dict[int, int] = {}
    for b in blocos:
        vistos[b["m"]] = vistos.get(b["m"], 0) + 1
    repetidos = {m: n for m, n in vistos.items() if n > 1}
    if repetidos:
        exemplos = ", ".join(f"m={m} ×{n}" for m, n in list(repetidos.items())[:4])
        ui.label(
            f"⚠ Padrão visível: {len(repetidos)} valor(es) de bloco se repetem ({exemplos}) e geram o MESMO c. "
            "Sem padding, quem olha o cifrado vê a repetição."
        ).classes("text-sm text-amber-800 bg-amber-50 rounded p-2")


def _detalhe_assinatura(ass: TraceEvent) -> None:
    d = ass.detalhes
    if "h" in d:
        ui.label(f"h = SHA-256(dados assinados) mod n = {d['h']}").classes("font-mono text-sm")
        ui.label(f"s = hᵈ mod n = {d['h']}^{d['d']} mod {d['n']} = {_int_b64(ass.saida)}").classes("font-mono text-sm")
        ui.label("Com n pequeno o hash é truncado (mod n): limitação proposital do modo didático.").classes("text-xs text-slate-500")
        _square_and_multiply(f"{d['h']}^{d['d']} mod {d['n']}", d.get("passos") or [], d["d"])
    else:
        ui.label(f"RSA-PSS com SHA-256 (n de {d.get('bits_n')} bits) · assinatura: {encurtar(str(ass.saida), 64)}").classes(
            "font-mono text-xs break-all"
        )
    ui.label("Dados assinados (todos os campos do envelope menos a assinatura, em JSON canônico):").classes("text-xs text-slate-500")
    ui.code(encurtar(d.get("dados_assinados", ""), 600), language="json").classes("w-full text-xs")


def _rede(rede: list) -> None:
    with secao("Rede (rastro do servidor)", "hub", "TraceEvents do servidor para esta mensagem: só metadados e cifrado."):
        if not rede:
            ui.label("Sem eventos de trânsito para esta mensagem.").classes("text-sm text-slate-500")
            return
        with ui.timeline(side="right", layout="dense", color="primary").classes("w-full"):
            for r in rede:
                icone = {"recebido": "move_to_inbox", "salto": "alt_route", "entregue": "outbox", "fila": "schedule", "confirmado": "done_all"}
                para = r.entrada.get("para") if isinstance(r.entrada, dict) else None
                destino = ", ".join(f"@{p}" for p in para) if isinstance(para, list) else (f"@{para}" if para else "")
                subtitulo = f"{r.ts.strftime('%H:%M:%S')}" + (f" · {r.duracao_ms:.2f} ms" if r.duracao_ms else "")
                with ui.timeline_entry(
                    title=f"{r.etapa} em {r.ator}" + (f" (para {destino})" if destino else ""),
                    subtitle=subtitulo,
                    icon=icone.get(r.etapa, "circle"),
                    color="warning" if r.etapa == "fila" else None,
                ):
                    saida = r.saida if isinstance(r.saida, str) else ", ".join(f"{k}: {v}" for k, v in (r.saida or {}).items())
                    ui.label(saida).classes("text-xs text-slate-600")


def _etapas_recebimento(recebimento: list[TraceEvent], rotulo: str) -> None:
    with secao(rotulo, "move_to_inbox", "Primeiro confere a assinatura com a pública do remetente; só então decifra com a própria privada."):
        ver = _primeiro(recebimento, "verificacao")
        if ver:
            d = ver.detalhes
            with ui.expansion("Verificação da assinatura: " + ("✓ confere" if ver.saida else "✗ não confere"), icon="verified").classes("w-full"):
                if "h" in d:
                    resultado = d["passos"][-1].get("multiplica", d["passos"][-1]["quadrado"]) if d.get("passos") else "?"
                    ui.label(f"sᵉ mod n = {d['s']}^{d['e']} mod {d['n']} = {resultado}").classes("font-mono text-sm")
                    ui.label(f"H(dados) mod n = {d['h']}  →  {'iguais: assinatura válida' if ver.saida else 'diferentes: rejeitada'}").classes(
                        "font-mono text-sm"
                    )
                    _square_and_multiply(f"{d['s']}^{d['e']} mod {d['n']}", d.get("passos") or [], d["e"])
                else:
                    ui.label(f"RSA-PSS SHA-256 com a pública do remetente (n de {d.get('bits_n')} bits): "
                             + ("válida" if ver.saida else "inválida")).classes("text-sm")
                if "erro" in d:
                    ui.label(d["erro"]).classes("text-sm text-red-700")
        dec = _primeiro(recebimento, "decifragem")
        if dec:
            d = dec.detalhes
            with ui.expansion("Decifragem bloco a bloco", icon="lock_open").classes("w-full"):
                blocos = d.get("blocos", [])
                if "d" in d:
                    ui.label(f"m = cᵈ mod n   com d = {d['d']} (privado, só neste aparelho) e n = {d['n']}").classes("font-mono text-sm")
                    _tabela(["#", "c", "m = cᵈ mod n", "bytes"], [[i + 1, b["c"], b["m"], b["bloco_hex"]] for i, b in enumerate(blocos)])
                    for i, b in enumerate(blocos[:MAX_TABELAS_SM]):
                        _square_and_multiply(f"Bloco {i + 1}: {b['c']}^{d['d']} mod {d['n']} = {b['m']}", b.get("passos") or [], d["d"])
                else:
                    ui.label(f"RSA-OAEP: cada bloco de {d.get('bits_n', 2048) // 8} bytes volta ao bloco original.").classes("text-sm")
                    _tabela(["#", "bloco decifrado (hex)"], [[i + 1, encurtar(b["bloco_hex"], 60)] for i, b in enumerate(blocos)])
                if "erro" in d:
                    ui.label(d["erro"]).classes("text-sm text-red-700")
        txt = _primeiro(recebimento, "decodificacao")
        if txt:
            with ui.expansion("Decodificação: bytes → JSON → texto", icon="chat").classes("w-full"):
                ui.label(f"texto: “{txt.saida}”" if txt.saida else txt.detalhes.get("erro", "")).classes("text-sm")
                ui.label("from e message_id internos conferidos com o envelope externo.").classes("text-xs text-slate-500")


def _linha_do_tempo(eventos: list[TraceEvent]) -> None:
    if not eventos:
        return
    with secao("Linha do tempo", "timer", "Duração de cada etapa neste aparelho."):
        maior = max(e.duracao_ms for e in eventos) or 1
        for e in eventos:
            para = e.entrada.get("para") if isinstance(e.entrada, dict) else None
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.icon(ICONE_ETAPA.get(e.etapa, "circle"), color="primary").classes("text-base")
                ui.label(NOME_ETAPA.get(e.etapa, e.etapa) + (f" (@{para})" if para else "")).classes("text-sm w-56 shrink-0")
                with ui.element("div").classes("grow h-3 bg-slate-100 rounded"):
                    ui.element("div").classes("h-3 bg-teal-600 rounded").style(f"width: {max(e.duracao_ms / maior * 100, 1):.1f}%")
                ui.label(f"{e.duracao_ms:.2f} ms").classes("text-xs font-mono w-20 text-right shrink-0")


def _experimentos(envelope: Envelope, privada, publica_remetente) -> None:
    with secao(
        "Experimentos",
        "science",
        "Simulações locais com este envelope (nada é enviado): o que acontece com a chave errada ou com um bit alterado.",
    ):
        resultado = ui.column().classes("w-full")

        async def chave_errada() -> None:
            resultado.clear()
            with resultado:
                ui.spinner()
            if envelope.mode == "didatico":
                outra = rsa_didatico.gerar(privada.n.bit_length())
            else:
                outra = await asyncio.to_thread(rsa_real.gerar)
            _mostrar(resultado, inspecao.decifrar_com_outra_chave(envelope, outra))

        def adulterar() -> None:
            _mostrar(resultado, inspecao.adulterar_e_verificar(envelope, publica_remetente))

        with ui.row():
            ui.button("Decifrar com a chave de outra pessoa", icon="key_off", on_click=chave_errada).props("outline").mark(
                "experimento-chave-errada"
            )
            ui.button("Trocar 1 bit e verificar a assinatura", icon="gpp_bad", on_click=adulterar).props("outline").mark(
                "experimento-adulterar"
            )


def _mostrar(resultado: ui.column, experimento: inspecao.Experimento) -> None:
    resultado.clear()
    with resultado:
        ui.label(experimento.titulo).classes("font-bold")
        if experimento.linhas:
            colunas = list(experimento.linhas[0])
            _tabela(colunas, [[_formatar(linha[c]) for c in colunas] for linha in experimento.linhas[:40]])
        if experimento.texto_obtido is not None:
            ui.label(f"Texto obtido: “{encurtar(experimento.texto_obtido, 120)}”").classes("font-mono text-sm text-red-700 break-all")
        ui.label(experimento.conclusao).classes("text-sm text-slate-700").mark("experimento-conclusao")


# ---------------------------------------------------------------- componentes


def _square_and_multiply(titulo: str, passos: list[dict], expoente: int) -> None:
    """Uma linha por bit do expoente: elevar ao quadrado sempre; multiplicar pela base quando o bit é 1."""
    if not passos:
        return
    with ui.expansion(f"Square-and-multiply · {titulo}", icon="calculate").classes("w-full bg-slate-50 rounded"):
        ui.label(f"expoente {expoente} em binário: {bin(expoente)[2:]}").classes("font-mono text-xs")
        _tabela(
            ["passo", "bit", "r² mod n", "× base mod n"],
            [[i + 1, p["bit"], p["quadrado"], p.get("multiplica", "—")] for i, p in enumerate(passos)],
        )


def _tabela(colunas: list[str], linhas: list[list]) -> None:
    ui.table(
        columns=[{"name": str(i), "label": c, "field": str(i), "align": "left"} for i, c in enumerate(colunas)],
        rows=[{str(i): _formatar(v) for i, v in enumerate(linha)} for linha in linhas],
        pagination={"rowsPerPage": 12},
    ).props("dense flat bordered").classes("w-full text-xs font-mono")


def _formatar(valor) -> str:
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return str(valor)


def _bytes_b64(texto: str) -> int:
    return len(base64.b64decode(texto))


def _int_b64(texto: str) -> int:
    return int.from_bytes(base64.b64decode(texto), "big")
