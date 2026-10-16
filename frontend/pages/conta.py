"""Telas do Passo 0: cadastro (gera as chaves), login e minhas chaves + busca no diretório."""

from __future__ import annotations

import re

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.pages.layout import cabecalho, mensagem_erro
from frontend.sessao import Sessao
from shared.crypto.chaves import carregar_publica
from shared.crypto.rsa_didatico import GeracaoDidatica
from shared.schemas import RegistroOut

USERNAME = re.compile(r"^[a-z0-9_]{3,20}$")
BITS_DIDATICO = {16: "16 bits", 24: "24 bits", 32: "32 bits", 48: "48 bits", 64: "64 bits"}


def registrar_paginas(sessao: Sessao) -> None:
    @ui.page("/cadastro")
    def cadastro() -> None:
        cabecalho(sessao)
        with ui.card().classes("w-full max-w-md mx-auto"):
            ui.label("Criar conta — Passo 0").classes("text-xl font-bold")
            ui.label(
                "Os pares de chaves são gerados neste aparelho. Só as chaves públicas vão para o servidor; "
                "as privadas ficam no keystore local."
            ).classes("text-sm text-gray-600")
            username = ui.input(
                "Usuário", validation={"3 a 20 caracteres: a-z, 0-9 ou _": lambda v: bool(USERNAME.fullmatch(v.strip().lower()))}
            ).classes("w-full")
            nome = ui.input("Nome").classes("w-full")
            senha = ui.input("Senha (mín. 6)", password=True, password_toggle_button=True).classes("w-full")
            bits = ui.select(BITS_DIDATICO, value=32, label="Tamanho da chave didática").classes("w-full")
            botao = ui.button("Gerar chaves e cadastrar").classes("w-full")
        resultado = ui.column().classes("w-full max-w-3xl mx-auto")

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
            ui.notify("Conta criada e chaves publicadas", type="positive")
            resultado.clear()
            with resultado:
                _mostrar_geracao(geracao, registro)
                ui.button("Ir para minhas chaves", on_click=lambda: ui.navigate.to("/"))

        botao.on_click(enviar)

    @ui.page("/login")
    def login() -> None:
        cabecalho(sessao)
        with ui.card().classes("w-full max-w-sm mx-auto"):
            ui.label("Entrar").classes("text-xl font-bold")
            username = ui.input("Usuário").classes("w-full")
            senha = ui.input("Senha", password=True, password_toggle_button=True).classes("w-full")

            async def entrar() -> None:
                try:
                    tem_chaves = await sessao.entrar(username.value, senha.value)
                except (ErroApi, httpx.HTTPError) as erro:
                    ui.notify(mensagem_erro(erro), type="negative")
                    return
                if not tem_chaves:
                    ui.notify("Este aparelho não tem as suas chaves privadas: não será possível decifrar mensagens.", type="warning")
                ui.navigate.to("/")

            senha.on("keydown.enter", entrar)
            ui.button("Entrar", on_click=entrar).classes("w-full")
            ui.link("Criar conta", "/cadastro")

    @ui.page("/")
    async def inicio():
        if not sessao.logado:
            return RedirectResponse("/login")
        cabecalho(sessao)
        with ui.column().classes("w-full max-w-4xl mx-auto"):
            ui.label(f"Olá, {sessao.usuario.nome}").classes("text-2xl font-bold")
            await _minhas_chaves(sessao)
            _diretorio(sessao)


def _mostrar_geracao(geracao: GeracaoDidatica, registro: RegistroOut) -> None:
    """Tabela da seção 6.4 do plano com os números da chave recém-gerada."""
    with ui.card().classes("w-full"):
        ui.label("Geração da chave didática").classes("text-lg font-bold")
        linhas = [
            {"grandeza": "p, q", "valor": f"{geracao.p}, {geracao.q}", "como": "primos sorteados (Miller-Rabin)"},
            {"grandeza": "n", "valor": str(geracao.n), "como": f"p × q ({geracao.n.bit_length()} bits) — público"},
            {"grandeza": "φ(n)", "valor": str(geracao.phi), "como": f"(p − 1)(q − 1) = {geracao.p - 1} × {geracao.q - 1}"},
            {"grandeza": "e", "valor": str(geracao.e), "como": f"mdc({geracao.e}, {geracao.phi}) = 1 — público"},
            {"grandeza": "d", "valor": str(geracao.d), "como": f"e⁻¹ mod φ: {geracao.e} × {geracao.d} mod {geracao.phi} = 1 — privado"},
        ]
        ui.table(
            columns=[
                {"name": "grandeza", "label": "Grandeza", "field": "grandeza", "align": "left"},
                {"name": "valor", "label": "Valor", "field": "valor", "align": "left"},
                {"name": "como", "label": "Como obter", "field": "como", "align": "left"},
            ],
            rows=linhas,
            row_key="grandeza",
        ).classes("w-full")
        ui.label("p, q e φ(n) são descartados: só (e, n) foi publicado, e d ficou no keystore.").classes("text-sm text-gray-600")
    for chave in registro.chaves:
        _cartao_chave(chave.modo, chave.public_key, "publicada")


def _cartao_chave(modo: str, public_key: str, rotulo: str) -> None:
    publica = carregar_publica(public_key)
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.badge(modo, color="teal" if modo == "real" else "orange")
            ui.label(publica.key_id).classes("font-mono")
            ui.badge(rotulo, color="gray")
        ui.label(f"Fingerprint: {publica.fingerprint_formatado}").classes("font-mono text-xs")
        ui.label(f"Número de segurança: {publica.numero_seguranca}").classes("font-mono text-xs")
        if modo == "didatico":
            ui.label(f"e = {publica.e}, n = {publica.n}").classes("font-mono text-xs")
        else:
            ui.label(f"e = {publica.numeros['e']}, n com {publica.numeros['n'].bit_length()} bits").classes("font-mono text-xs")


async def _minhas_chaves(sessao: Sessao) -> None:
    ui.label("Minhas chaves").classes("text-lg font-bold mt-4")
    try:
        publicadas = await sessao.api.minhas_chaves()
    except (ErroApi, httpx.HTTPError) as erro:
        ui.notify(mensagem_erro(erro), type="negative")
        return
    locais = {c["key_id"] for c in sessao.keystore.listar()} if sessao.keystore else set()
    for chave in publicadas:
        no_aparelho = "privada neste aparelho" if chave.key_id in locais else "privada ausente"
        _cartao_chave(chave.modo, chave.public_key, f"{chave.status} · {no_aparelho}")


def _diretorio(sessao: Sessao) -> None:
    ui.label("Diretório de chaves públicas").classes("text-lg font-bold mt-4")
    with ui.row().classes("items-end gap-2"):
        usuarios = ui.input("Usuários (separados por vírgula)").classes("w-72")
        modo = ui.select({"real": "real", "didatico": "didático"}, value="real", label="Modo")
        botao = ui.button("Buscar")
    resultado = ui.column().classes("w-full")

    async def buscar() -> None:
        nomes = [u.strip() for u in (usuarios.value or "").split(",") if u.strip()]
        if not nomes:
            return
        try:
            diretorio = await sessao.api.buscar_chaves(nomes, modo.value)
        except (ErroApi, httpx.HTTPError) as erro:
            ui.notify(mensagem_erro(erro), type="negative")
            return
        resultado.clear()
        with resultado:
            for username, chave in diretorio.chaves.items():
                # confere que o key_id anunciado corresponde à chave entregue
                if carregar_publica(chave.public_key).key_id != chave.key_id:
                    ui.notify(f"A chave de {username} não confere com o key_id anunciado!", type="negative")
                    continue
                ui.label(f"@{username}").classes("font-bold")
                _cartao_chave(chave.modo, chave.public_key, chave.status)
            if diretorio.sem_chave:
                ui.label(f"Sem chave ativa neste modo: {', '.join(diretorio.sem_chave)}").classes("text-sm text-red-700")

    botao.on_click(buscar)
    usuarios.on("keydown.enter", buscar)
