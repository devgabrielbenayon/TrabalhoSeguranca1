"""Laboratório (RF18): quebrar uma chave pequena fatorando n, e o custo de cada tamanho de chave.

Tudo roda neste aparelho com dados públicos (a chave pública vem do diretório); nada vai para o servidor.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import medicoes
from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import conectar, mensagem_erro, moldura, secao, titulo_pagina
from frontend.sessao import Sessao
from shared.crypto import fatoracao
from shared.crypto.chaves import carregar_publica
from shared.crypto.rsa_didatico import PublicaDidatica

ALVOS_EXTRAPOLACAO = (128, 256, 512, 1024, 2048)


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/laboratorio")
    async def pagina():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        try:
            contatos = sorted(c.username for c in await sessao.api.clientes())
        except (ErroApi, httpx.HTTPError):
            contatos = []
        with moldura(sessao, mensageiro, "/laboratorio"):
            titulo_pagina(
                "Laboratório",
                "Por que o modo didático é inseguro e o real usa 2048 bits: quebre chaves pequenas e meça o custo de cada tamanho.",
                "science",
            )
            _quebrar_chave(sessao, contatos)
            with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
                _grafico_tamanhos()
                _grafico_fatoracao()


def _quebrar_chave(sessao: Sessao, contatos: list[str]) -> None:
    with secao(
        "Quebrar uma chave pública",
        "lock_open",
        "Com (e, n) públicos: fatorar n em p × q, calcular φ(n) e d = e⁻¹ mod φ(n). Com d, dá para ler tudo e assinar como o dono.",
    ):
        with ui.row().classes("items-end gap-2 flex-wrap"):
            usuario = ui.input("Usuário", autocomplete=contatos, placeholder="ex.: bob").classes("w-48").mark("lab-usuario")
            modo = ui.toggle({"didatico": "didático", "real": "real"}, value="didatico").props("dense no-caps")
            botao = ui.button("Buscar a chave e quebrar", icon="travel_explore").mark("lab-quebrar")
            ui.separator().props("vertical")
            n_manual = ui.input("ou informe n", placeholder="3233").classes("w-40").mark("lab-n")
            e_manual = ui.input("e", value="17").classes("w-20")
            manual = ui.button("Quebrar", icon="calculate").props("outline").mark("lab-quebrar-n")
            ui.button("Exemplo clássico (n = 3233)", on_click=lambda: (n_manual.set_value("3233"), e_manual.set_value("17"))).props(
                "flat no-caps"
            )
        resultado = ui.column().classes("w-full gap-1")

    async def pelo_diretorio() -> None:
        nome = (usuario.value or "").strip().lower()
        if not nome:
            return
        try:
            diretorio = await sessao.api.buscar_chaves([nome], modo.value)
        except (ErroApi, httpx.HTTPError) as erro:
            ui.notify(mensagem_erro(erro), type="negative")
            return
        if nome not in diretorio.chaves:
            ui.notify(f"@{nome} não tem chave {modo.value} ativa", type="warning")
            return
        publica = carregar_publica(diretorio.chaves[nome].public_key)
        if isinstance(publica, PublicaDidatica):
            await _mostrar_quebra(resultado, publica, f"chave didática de @{nome} ({publica.key_id})")
        else:
            _mostrar_inviavel(resultado, nome, publica.numeros["n"])

    async def pelo_numero() -> None:
        try:
            publica = PublicaDidatica(int(e_manual.value), int(n_manual.value))
            if not 4 <= publica.n < 1 << 128:
                raise ValueError("use um n entre 4 e 2¹²⁸ (acima disso o rho não termina a tempo)")
        except (TypeError, ValueError) as erro:
            ui.notify(f"n ou e inválido: {erro}", type="negative")
            return
        await _mostrar_quebra(resultado, publica, f"n = {publica.n}, e = {publica.e}")

    botao.on_click(pelo_diretorio)
    usuario.on("keydown.enter", pelo_diretorio)
    manual.on_click(pelo_numero)


async def _mostrar_quebra(resultado: ui.column, publica: PublicaDidatica, origem: str) -> None:
    resultado.clear()
    with resultado:
        ui.spinner()
    try:
        quebrada = await asyncio.to_thread(fatoracao.quebrar, publica)
    except (fatoracao.FatoracaoFalhou, ValueError) as erro:
        resultado.clear()
        with resultado:
            ui.label(f"Não foi possível: {erro}").classes("text-sm text-red-700")
        return
    f = quebrada.fatoracao
    m = 42 % publica.n
    c = pow(m, publica.e, publica.n)
    volta = pow(c, quebrada.d, publica.n)
    resultado.clear()
    with resultado:
        ui.label(f"Alvo: {origem} — n com {publica.n.bit_length()} bits").classes("font-bold")
        passos = [
            ("1. Fatorar n", f"{f.n} = {f.p} × {f.q}", f"{f.metodo}, {f.passos} passos, {f.duracao_ms:.2f} ms"),
            ("2. φ(n) = (p − 1)(q − 1)", f"{f.p - 1} × {f.q - 1} = {quebrada.phi}", ""),
            ("3. d = e⁻¹ mod φ(n)", f"d = {quebrada.d}", f"{publica.e} × {quebrada.d} mod {quebrada.phi} = 1"),
            ("4. Conferir", f"{m}^{publica.e} mod n = {c}  →  {c}^d mod n = {volta}", "✓ a chave privada foi recuperada" if volta == m else "✗"),
        ]
        for i, (titulo, conta, nota) in enumerate(passos):
            with ui.row().classes("items-baseline gap-3 w-full"):
                ui.label(titulo).classes("text-sm text-slate-600 w-48 shrink-0")
                ui.label(conta).classes("font-mono text-sm break-all").mark(f"lab-passo-{i + 1}")
                if nota:
                    ui.label(nota).classes("text-xs text-slate-500")
        ui.label(
            "Com d nas mãos, um atacante decifra qualquer mensagem enviada a esta chave e forja assinaturas do dono."
        ).classes("text-sm text-red-700")


def _mostrar_inviavel(resultado: ui.column, nome: str, n: int) -> None:
    resultado.clear()
    with resultado:
        ui.label(f"Chave real de @{nome}: n com {n.bit_length()} bits ({len(str(n))} dígitos decimais)").classes("font-bold")
        ui.label(f"n = {str(n)[:60]}…{str(n)[-20:]}").classes("font-mono text-xs break-all")
        ui.label(
            "Pollard rho levaria da ordem de 2^512 passos. Ataques reais usam o crivo de corpos numéricos (GNFS), e o maior "
            "número RSA fatorado publicamente tem 829 bits (RSA-250, em 2020, com ~2.700 anos-núcleo de computação)."
        ).classes("text-sm")
        ui.label("Meça abaixo e veja a extrapolação.").classes("text-sm text-slate-600")


def _grafico_tamanhos() -> None:
    with secao(
        "Gerar e usar chaves de cada tamanho",
        "bar_chart",
        "Implementação própria (Python: Miller-Rabin, Euclides, square-and-multiply) e a biblioteca cryptography (C).",
    ).classes("grow basis-96"):
        grafico = ui.echart(_opcoes_barras([], [])).classes("w-full").style("height: 320px")
        tabela = ui.column().classes("w-full")
        progresso = ui.label("").classes("text-xs text-slate-500")

        async def medir() -> None:
            botao.disable()
            resultados = []
            try:
                for bits in medicoes.TAMANHOS_GERACAO:
                    progresso.text = f"medindo {bits} bits…"
                    resultados.append(await asyncio.to_thread(medicoes.medir_chave, bits))
                    grafico.options.update(_opcoes_barras(resultados, medicoes.TAMANHOS_GERACAO))
                    grafico.update()
            finally:
                botao.enable()
            progresso.text = "Gerar cresce rápido com o tamanho (achar primos grandes); cifrar com e = 65537 é sempre barato."
            tabela.clear()
            with tabela:
                ui.table(
                    columns=[{"name": k, "label": r, "field": k, "align": "left"} for k, r in (
                        ("bits", "bits"), ("gerar", "gerar (própria)"), ("lib", "gerar (cryptography)"),
                        ("cifrar", "cifrar mᵉ"), ("decifrar", "decifrar cᵈ"),
                    )],
                    rows=[{
                        "bits": r.bits, "gerar": f"{r.geracao_ms:.1f} ms",
                        "lib": f"{r.biblioteca_geracao_ms:.1f} ms" if r.biblioteca_geracao_ms is not None else "— (mín. 1024)",
                        "cifrar": f"{r.cifrar_ms:.3f} ms", "decifrar": f"{r.decifrar_ms:.3f} ms",
                    } for r in resultados],
                ).props("dense flat bordered").classes("w-full text-xs")

        botao = ui.button("Medir", icon="speed", on_click=medir).mark("lab-medir")


def _opcoes_barras(resultados: list, tamanhos) -> dict:
    def serie(nome: str, valores: list) -> dict:
        return {"name": nome, "type": "bar", "data": [round(v, 3) if v is not None else None for v in valores]}

    return {
        **_dica_vazio(not resultados, "Clique em Medir"),
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0},
        "grid": {"left": 60, "right": 10, "top": 40, "bottom": 30},
        "xAxis": {"type": "category", "data": [f"{b} bits" for b in tamanhos]},
        "yAxis": {"type": "log", "name": "ms (escala log)", "nameLocation": "middle", "nameGap": 45, "min": 0.001},
        "series": [
            serie("gerar (própria)", [r.geracao_ms for r in resultados]),
            serie("gerar (cryptography)", [r.biblioteca_geracao_ms for r in resultados]),
            serie("decifrar 1 bloco", [max(r.decifrar_ms, 0.001) for r in resultados]),
            serie("cifrar 1 bloco", [max(r.cifrar_ms, 0.001) for r in resultados]),
        ],
    }


def _dica_vazio(vazio: bool, texto: str) -> dict:
    """Texto no meio do gráfico enquanto não há medições (o título some quando os dados chegam)."""
    return {"title": {"show": vazio, "text": texto, "left": "center", "top": "middle",
                      "textStyle": {"color": "#94a3b8", "fontSize": 14, "fontWeight": "normal"}}}


def _grafico_fatoracao() -> None:
    with secao(
        "Quanto custa fatorar n",
        "trending_up",
        "Pollard rho em chaves didáticas de 16 a 64 bits. O custo cresce com n^(1/4): +4 bits ≈ ×2 no tempo.",
    ).classes("grow basis-96"):
        grafico = ui.echart(_opcoes_linha({})).classes("w-full").style("height: 320px")
        extrapolacao = ui.column().classes("w-full gap-0")

        async def medir() -> None:
            botao.disable()
            medidas: dict[int, float] = {}
            try:
                for bits in medicoes.TAMANHOS_FATORACAO:
                    medidas[bits] = await asyncio.to_thread(medicoes.medir_fatoracao, bits)
                    grafico.options.update(_opcoes_linha(medidas))
                    grafico.update()
            finally:
                botao.enable()
            maior = max(medidas)
            extrapolacao.clear()
            with extrapolacao:
                ui.label(f"Extrapolando a partir de {maior} bits ({medidas[maior]:.1f} ms):").classes("text-sm font-bold")
                for alvo in ALVOS_EXTRAPOLACAO:
                    estimativa = medicoes.log10_tempo_fatoracao(maior, medidas[maior], alvo)
                    with ui.row().classes("gap-2"):
                        ui.label(f"{alvo} bits").classes("text-sm w-20")
                        ui.label(medicoes.formatar_log10_ms(estimativa)).classes(
                            "text-sm font-mono " + ("text-red-700" if alvo <= 128 else "text-green-800")
                        ).mark(f"lab-extrapolacao-{alvo}")
                ui.label(
                    "Só para comparar: a idade do universo é ~1,4 × 10^10 anos. O rho não é o melhor ataque, mas mesmo o GNFS "
                    "não alcança 2048 bits."
                ).classes("text-xs text-slate-500")

        botao = ui.button("Medir fatoração", icon="timer", on_click=medir).mark("lab-medir-fatoracao")


def _opcoes_linha(medidas: dict[int, float]) -> dict:
    bits = list(medicoes.TAMANHOS_FATORACAO)
    teorica = []
    if medidas:
        base_bits = max(medidas)
        teorica = [round(10 ** medicoes.log10_tempo_fatoracao(base_bits, medidas[base_bits], b), 4) for b in bits]
    return {
        **_dica_vazio(not medidas, "Clique em Medir fatoração"),
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0},
        "grid": {"left": 60, "right": 50, "top": 40, "bottom": 30},
        "xAxis": {"type": "category", "data": [f"{b}" for b in bits], "name": "bits de n"},
        "yAxis": {"type": "log", "name": "ms (escala log)", "nameLocation": "middle", "nameGap": 45, "min": 0.001},
        "series": [
            {"name": "medido", "type": "line", "symbolSize": 8,
             "data": [round(max(medidas[b], 0.001), 4) if b in medidas else None for b in bits]},
            {"name": "modelo n^(1/4)", "type": "line", "lineStyle": {"type": "dashed"}, "showSymbol": False,
             "data": [max(v, 0.001) for v in teorica] if teorica else []},
        ],
    }
