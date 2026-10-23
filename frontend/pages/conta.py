"""Telas do Passo 0: cadastro (gera o par de chaves neste aparelho) e login."""

from __future__ import annotations

import re

import httpx
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.pages.layout import (
    avatar,
    cartao,
    icone_destaque,
    logotipo,
    mensagem_erro,
    MODO,
    numero_seguranca,
    pilula,
    tema,
)
from frontend.sessao import Sessao
from shared.crypto.chaves import carregar_publica

USERNAME = re.compile(r"^[a-z0-9_]{3,20}$")
# (ícone, título, texto) do painel de apresentação
DESTAQUES = (
    ("vpn_key", "O par de chaves nasce aqui", "A chave privada fica neste aparelho, guardada com a sua senha."),
    ("cloud_upload", "Só a pública vai ao servidor", "Junto com uma assinatura que prova que você tem a privada."),
    ("lock", "Cada mensagem sai cifrada e assinada", "No caminho, servidor e nós só veem bytes embaralhados."),
)


def registrar_paginas(sessao: Sessao) -> None:
    @ui.page("/cadastro")
    def cadastro() -> None:
        with _tela_de_acesso():
            formulario = ui.column().classes("w-full max-w-md gap-4")
            with formulario:
                _cabecalho("Criar conta", "Passo 0: o seu par de chaves (RSA 2048 bits) é gerado agora, neste aparelho.")
                username = _campo(ui.input(
                    "Usuário", validation={"3 a 20 caracteres: a-z, 0-9 ou _": lambda v: bool(USERNAME.fullmatch(v.strip().lower()))}
                ), "alternate_email").mark("cadastro-usuario")
                nome = _campo(ui.input("Nome"), "badge").mark("cadastro-nome")
                senha = _campo(ui.input("Senha (mín. 6)", password=True, password_toggle_button=True), "lock").mark("cadastro-senha")
                botao = ui.button("Gerar chaves e criar conta", icon="auto_awesome").props("unelevated no-caps size=lg").classes(
                    "w-full rounded-xl"
                ).mark("cadastro-enviar")
                _rodape("Já tem conta?", "Entrar", "/login")
            resultado = ui.column().classes("w-full max-w-2xl gap-4")

        async def enviar() -> None:
            botao.disable()
            botao.text = "Gerando chaves…"
            try:
                registro, _ = await sessao.cadastrar(username.value, nome.value, senha.value)
            except (ErroApi, ValueError, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative", multi_line=True)
                return
            finally:
                botao.enable()
                botao.text = "Gerar chaves e criar conta"
            ui.notify("Conta criada e chave pública publicada", type="positive")
            formulario.set_visibility(False)
            resultado.clear()
            with resultado:
                with ui.row().classes("items-center gap-3 no-wrap surgir"):
                    icone_destaque("celebration", "ok", "text-2xl")
                    with ui.column().classes("gap-0"):
                        ui.label(f"Bem-vindo, {nome.value}!").classes("text-2xl font-bold txt-tinta")
                        ui.label("Sua chave pública já está no servidor; a privada ficou aqui.").classes(
                            "text-sm text-stone-500"
                        )
                for chave in registro.chaves:
                    if chave.modo == MODO:
                        _cartao_publicada(chave.public_key)
                with ui.row().classes("gap-2"):
                    ui.button("Ir para o chat", icon="forum", on_click=lambda: ui.navigate.to("/chat")).props("unelevated no-caps")
                    ui.button("Minhas chaves", icon="vpn_key", on_click=lambda: ui.navigate.to("/chaves")).props("outline no-caps")

        botao.on_click(enviar)

    @ui.page("/login")
    def login() -> None:
        with _tela_de_acesso():
            with ui.column().classes("w-full max-w-sm gap-4"):
                _cabecalho("Bem-vindo de volta", "A senha também abre o keystore deste aparelho, onde estão as suas chaves privadas.")
                locais = _contas_neste_aparelho(sessao)
                if locais:
                    with ui.column().classes("w-full gap-2"):
                        ui.label("Contas com chaves neste aparelho").classes("rotulo")
                        with ui.row().classes("gap-2 flex-wrap"):
                            for nome_local in locais:
                                with ui.row().classes(
                                    "clicavel items-center gap-2 no-wrap rounded-full pl-1 pr-3 py-1 ring-1 ring-stone-200 bg-white cursor-pointer"
                                ).on("click", lambda n=nome_local: (username.set_value(n), senha.run_method("focus"))):
                                    avatar(nome_local, tamanho=7)
                                    ui.label(f"@{nome_local}").classes("text-sm font-medium txt-tinta")
                username = _campo(ui.input("Usuário"), "person").mark("login-usuario")
                senha = _campo(ui.input("Senha", password=True, password_toggle_button=True), "lock").mark("login-senha")

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
                ui.button("Entrar", icon="login", on_click=entrar).props("unelevated no-caps size=lg").classes(
                    "w-full rounded-xl"
                ).mark("login-entrar")
                _rodape("Novo por aqui?", "Criar conta", "/cadastro")


# ---------------------------------------------------------------- moldura das telas de acesso


def _tela_de_acesso() -> ui.column:
    """Metade com a apresentação do app (degradê da paleta) e metade com o formulário. Devolve a coluna do formulário."""
    tema()
    ui.query(".nicegui-content").classes("p-0 gap-0")
    with ui.row().classes("w-full min-h-screen no-wrap gap-0 items-stretch"):
        with ui.column().classes("degrade relative overflow-hidden justify-between gap-10 p-12 max-lg:hidden").style("width: 44%"):
            ui.icon("enhanced_encryption").classes("absolute opacity-10 txt-tinta").style(
                "font-size: 320px; right: -60px; bottom: -40px"
            )
            logotipo(grande=True)
            with ui.column().classes("gap-3 max-w-md"):
                ui.label("Mensagens que só quem deve consegue ler.").classes("text-4xl font-bold txt-tinta leading-tight")
                ui.label("Cifradas e assinadas com RSA de ponta a ponta. Veja cada passo acontecendo.").classes(
                    "text-base txt-tinta opacity-80"
                )
            with ui.column().classes("gap-3 w-full"):
                for i, (icone, titulo, texto) in enumerate(DESTAQUES):
                    with ui.row().classes(
                        "w-full items-center gap-3 no-wrap rounded-2xl bg-white/60 px-4 py-3 max-w-md shadow-sm surgir"
                    ).style(f"animation-delay: {0.15 + i * 0.15:.2f}s"):
                        with ui.element("div").classes("rounded-xl bg-white p-2 flex shrink-0"):
                            ui.icon(icone, color="primary")
                        with ui.column().classes("gap-0"):
                            ui.label(titulo).classes("font-semibold txt-tinta")
                            ui.label(texto).classes("text-xs txt-tinta opacity-75")
            ui.label("Trabalho 1 de Segurança da Informação · UEA").classes("text-xs txt-tinta opacity-60")
        formulario = ui.column().classes("grow items-center justify-center gap-6 p-6 md:p-10")
        with formulario:
            with ui.row().classes("lg:hidden"):
                logotipo()
    return formulario


def _cabecalho(titulo: str, subtitulo: str) -> None:
    with ui.column().classes("gap-1"):
        ui.label(titulo).classes("text-3xl font-bold txt-tinta")
        ui.label(subtitulo).classes("text-sm text-stone-500")


def _campo(campo: ui.input, icone: str) -> ui.input:
    campo.props("outlined").classes("w-full")
    with campo.add_slot("prepend"):
        ui.icon(icone, color="grey-6")
    return campo


def _rodape(pergunta: str, acao: str, rota: str) -> None:
    with ui.row().classes("w-full justify-center items-center gap-1 text-sm"):
        ui.label(pergunta).classes("text-stone-500")
        ui.link(acao, rota).classes("font-semibold txt-tinta")


def _contas_neste_aparelho(sessao: Sessao) -> list[str]:
    if not sessao.raiz_keystore.is_dir():
        return []
    return sorted(p.name for p in sessao.raiz_keystore.iterdir() if (p / "index.json").exists())


# ---------------------------------------------------------------- depois do cadastro


def _cartao_publicada(public_key: str) -> None:
    publica = carregar_publica(public_key)
    with cartao("w-full p-5 gap-2 surgir"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("key", color="primary")
            ui.label(publica.key_id).classes("font-mono txt-tinta")
            pilula("publicada", "ok", "cloud_done")
        ui.label(f"Fingerprint: {publica.fingerprint_formatado}").classes("font-mono text-xs text-stone-500 quebra")
        numero_seguranca(publica.numero_seguranca)
