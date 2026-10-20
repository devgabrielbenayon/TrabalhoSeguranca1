"""Telas do Passo 0: cadastro (gera as chaves neste aparelho, com a animação da geração) e login."""

from __future__ import annotations

import re

import httpx
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.pages.layout import mensagem_erro, moldura, numero_seguranca, selo_modo
from frontend.sessao import Sessao
from shared.crypto.chaves import carregar_publica
from shared.crypto.rsa_didatico import GeracaoDidatica

USERNAME = re.compile(r"^[a-z0-9_]{3,20}$")
BITS_DIDATICO = {16: "16 bits", 24: "24 bits", 32: "32 bits", 48: "48 bits", 64: "64 bits"}
PAUSA_ANIMACAO = 0.35


def registrar_paginas(sessao: Sessao) -> None:
    @ui.page("/cadastro")
    def cadastro() -> None:
        conteudo = moldura(sessao)
        with conteudo.classes("items-center"):
            with ui.card().classes("w-full max-w-md shadow-md"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("key", color="primary").classes("text-3xl")
                    ui.label("Criar conta — Passo 0").classes("text-xl font-bold")
                ui.label(
                    "Os pares de chaves (real e didático) são gerados aqui, neste aparelho. Só as chaves públicas "
                    "vão para o servidor, junto com uma assinatura que prova que você tem as privadas."
                ).classes("text-sm text-slate-600")
                username = ui.input(
                    "Usuário", validation={"3 a 20 caracteres: a-z, 0-9 ou _": lambda v: bool(USERNAME.fullmatch(v.strip().lower()))}
                ).classes("w-full").mark("cadastro-usuario")
                nome = ui.input("Nome").classes("w-full").mark("cadastro-nome")
                senha = ui.input("Senha (mín. 6)", password=True, password_toggle_button=True).classes("w-full").mark("cadastro-senha")
                bits = ui.select(BITS_DIDATICO, value=32, label="Tamanho da chave didática").classes("w-full")
                ui.label("A chave real tem sempre 2048 bits (RSA-OAEP + PSS).").classes("text-xs text-slate-500")
                botao = ui.button("Gerar chaves e cadastrar", icon="auto_awesome").classes("w-full").mark("cadastro-enviar")
                with ui.row().classes("w-full justify-center text-sm"):
                    ui.label("Já tem conta?")
                    ui.link("Entrar", "/login")
            resultado = ui.column().classes("w-full max-w-4xl")

        async def enviar() -> None:
            botao.disable()
            botao.text = "Gerando chaves…"
            try:
                registro, geracao = await sessao.cadastrar(username.value, nome.value, senha.value, bits.value)
            except (ErroApi, ValueError, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative", multi_line=True)
                return
            finally:
                botao.enable()
                botao.text = "Gerar chaves e cadastrar"
            ui.notify("Conta criada e chaves públicas publicadas", type="positive")
            resultado.clear()
            with resultado:
                _animar_geracao(geracao)
                for chave in registro.chaves:
                    _cartao_publicada(chave.modo, chave.public_key)
                with ui.row():
                    ui.button("Ir para o chat", icon="forum", on_click=lambda: ui.navigate.to("/chat"))
                    ui.button("Minhas chaves", icon="vpn_key", on_click=lambda: ui.navigate.to("/chaves")).props("outline")

        botao.on_click(enviar)

    @ui.page("/login")
    def login() -> None:
        conteudo = moldura(sessao)
        with conteudo.classes("items-center"):
            with ui.card().classes("w-full max-w-sm shadow-md"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("lock_open", color="primary").classes("text-3xl")
                    ui.label("Entrar").classes("text-xl font-bold")
                ui.label("A senha também abre o keystore local, onde estão suas chaves privadas.").classes(
                    "text-sm text-slate-600"
                )
                username = ui.input("Usuário").classes("w-full").mark("login-usuario")
                senha = ui.input("Senha", password=True, password_toggle_button=True).classes("w-full").mark("login-senha")

                locais = _contas_neste_aparelho(sessao)
                if locais:
                    ui.label("Contas com chaves neste aparelho:").classes("text-xs text-slate-500")
                    with ui.row().classes("gap-1"):
                        for nome_local in locais:
                            ui.chip(nome_local, icon="person", on_click=lambda n=nome_local: username.set_value(n)).props(
                                "clickable dense outline color=primary"
                            )

                async def entrar() -> None:
                    try:
                        tem_chaves = await sessao.entrar(username.value, senha.value)
                    except (ErroApi, httpx.HTTPError) as erro:
                        ui.notify(mensagem_erro(erro), type="negative")
                        return
                    if not tem_chaves:
                        ui.notify("Este aparelho não tem as suas chaves privadas: não será possível decifrar mensagens.", type="warning")
                    ui.navigate.to("/chat")

                senha.on("keydown.enter", entrar)
                ui.button("Entrar", icon="login", on_click=entrar).classes("w-full").mark("login-entrar")
                with ui.row().classes("w-full justify-center text-sm"):
                    ui.label("Novo por aqui?")
                    ui.link("Criar conta", "/cadastro")


def _contas_neste_aparelho(sessao: Sessao) -> list[str]:
    if not sessao.raiz_keystore.is_dir():
        return []
    return sorted(p.name for p in sessao.raiz_keystore.iterdir() if (p / "index.json").exists())


def _animar_geracao(geracao: GeracaoDidatica) -> None:
    """Os passos da seção 6.1 do plano aparecendo um a um (no navegador), com os números da chave recém-gerada."""
    passos = [
        ("casino", "1. Sortear dois primos p e q (Miller-Rabin)", f"p = {geracao.p}   q = {geracao.q}"),
        ("close", "2. n = p × q — o módulo, público", f"n = {geracao.p} × {geracao.q} = {geracao.n}  ({geracao.n.bit_length()} bits)"),
        ("functions", "3. φ(n) = (p − 1)(q − 1)", f"φ(n) = {geracao.p - 1} × {geracao.q - 1} = {geracao.phi}"),
        ("lock_open", "4. Escolher e com mdc(e, φ(n)) = 1 — público", f"e = {geracao.e}"),
        ("vpn_key", "5. d = e⁻¹ mod φ(n) (Euclides estendido) — privado", f"{geracao.e} × {geracao.d} mod {geracao.phi} = 1  →  d = {geracao.d}"),
        ("publish", "6. Publicar (e, n); guardar d; descartar p, q e φ(n)", f"pública = ({geracao.e}, {geracao.n})   privada = ({geracao.d}, {geracao.n})"),
    ]
    with ui.card().classes("w-full shadow-sm"):
        ui.label("Geração da chave didática").classes("text-lg font-bold")
        with ui.timeline(side="right", layout="comfortable", color="primary").classes("w-full"):
            for i, (icone, titulo, conta) in enumerate(passos):
                with ui.timeline_entry(title=titulo, icon=icone).classes("surgir").style(f"animation-delay: {i * PAUSA_ANIMACAO}s"):
                    ui.label(conta).classes("font-mono text-sm bg-slate-50 rounded px-2 py-1")
        ui.label("p, q e φ(n) foram descartados: só (e, n) foi publicado, e d ficou no keystore deste aparelho.").classes(
            "text-sm text-slate-600 surgir"
        ).style(f"animation-delay: {len(passos) * PAUSA_ANIMACAO}s")


def _cartao_publicada(modo: str, public_key: str) -> None:
    publica = carregar_publica(public_key)
    with ui.card().classes("w-full shadow-sm"):
        with ui.row().classes("items-center gap-2"):
            selo_modo(modo)
            ui.label(publica.key_id).classes("font-mono")
            ui.badge("publicada", color="positive")
        ui.label(f"Fingerprint: {publica.fingerprint_formatado}").classes("font-mono text-xs")
        numero_seguranca(publica.numero_seguranca)
