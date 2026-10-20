"""Gerenciador de chaves: chave ativa de cada modo, troca (5.4), exclusão (5.5), histórico,
keystore local (com "apagar privada") e busca no diretório de chaves públicas."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import NOME_CHAVE, conectar, mensagem_erro, moldura, numero_seguranca, secao, selo_modo, titulo_pagina
from frontend.sessao import Sessao
from shared.crypto.chaves import carregar_publica

COR_STATUS = {"ativa": "positive", "substituida": "grey-7", "revogada": "negative"}


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/chaves")
    async def chaves():
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        try:
            publicadas = await sessao.api.minhas_chaves()
        except (ErroApi, httpx.HTTPError) as erro:
            ui.notify(mensagem_erro(erro), type="negative")
            publicadas = []
        locais = {c["key_id"]: c for c in sessao.keystore.listar()} if sessao.keystore else {}
        with moldura(sessao, mensageiro, "/chaves"):
            titulo_pagina("Minhas chaves", "Uma chave ativa por modo. A privada fica só no keystore deste aparelho.", "vpn_key")

            with ui.row().classes("w-full gap-4 items-stretch"):
                for modo in ("real", "didatico"):
                    ativa = next((c for c in publicadas if c.modo == modo and c.status == "ativa"), None)
                    _cartao_modo(sessao, modo, ativa, ativa is not None and ativa.key_id in locais)

            with secao("Histórico das minhas chaves", "history", "Chaves trocadas continuam no keystore: as mensagens antigas seguem legíveis."):
                for chave in reversed(publicadas):
                    no_aparelho = "privada neste aparelho" if chave.key_id in locais else "privada ausente"
                    with ui.row().classes("items-center gap-2 w-full border-b border-slate-100 py-1"):
                        selo_modo(chave.modo)
                        ui.label(chave.key_id).classes("font-mono text-sm")
                        ui.badge(chave.status, color=COR_STATUS[chave.status])
                        ui.label(f"{chave.status} · {no_aparelho}").classes("text-sm text-slate-600")
                        ui.space()
                        ui.label(chave.criada_em.strftime("%d/%m %H:%M")).classes("text-xs text-slate-500")

            _keystore_local(sessao, locais)
            _diretorio(sessao)


def _cartao_modo(sessao: Sessao, modo: str, ativa, privada_aqui: bool) -> None:
    descricao = "RSA-OAEP 2048 + PSS (cryptography)" if modo == "real" else "RSA de livro, números legíveis (implementação própria)"
    with ui.card().classes("grow basis-80 shadow-sm"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("enhanced_encryption" if modo == "real" else "school", color="primary").classes("text-2xl")
            ui.label(NOME_CHAVE[modo].capitalize()).classes("text-lg font-bold")
            selo_modo(modo)
        ui.label(descricao).classes("text-xs text-slate-500 -mt-2")
        if ativa is None:
            ui.label("Nenhuma chave ativa: ninguém consegue cifrar para você neste modo.").classes("text-sm text-red-700")
        else:
            publica = carregar_publica(ativa.public_key)
            ui.label(ativa.key_id).classes("font-mono font-bold")
            ui.label(f"Fingerprint {publica.fingerprint_formatado}").classes("font-mono text-xs break-all")
            ui.label("Número de segurança").classes("text-xs text-slate-500")
            numero_seguranca(publica.numero_seguranca)
            if modo == "didatico":
                ui.label(f"e = {publica.e}   n = {publica.n}  ({publica.n.bit_length()} bits)").classes("font-mono text-xs")
            else:
                ui.label(f"e = {publica.numeros['e']}   n com {publica.numeros['n'].bit_length()} bits").classes("font-mono text-xs")
            if not privada_aqui:
                ui.label("⚠ a privada desta chave não está neste aparelho").classes("text-xs text-amber-800")

        async def trocar() -> None:
            ui.notify("Gerando o novo par e assinando o desafio do servidor…")
            try:
                saida, _ = await sessao.trocar_chave(modo)
            except (ErroApi, ValueError, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            ui.notify(f"Nova chave {saida.key_id} publicada; os contatos foram avisados", type="positive")
            ui.navigate.to("/chaves")

        with ui.row().classes("mt-auto pt-2"):
            ui.button("Trocar chave" if ativa else "Publicar nova chave", icon="autorenew", on_click=trocar).props(
                "outline"
            ).mark(f"trocar-{modo}")
            if ativa:
                ui.button("Excluir chave", icon="delete_forever", on_click=lambda: _dialogo_exclusao(sessao, modo)).props(
                    "outline color=negative"
                ).mark(f"excluir-{modo}")


def _dialogo_exclusao(sessao: Sessao, modo: str) -> None:
    with ui.dialog() as dialogo, ui.card():
        ui.label(f"Excluir a {NOME_CHAVE[modo]}").classes("text-lg font-bold")
        ui.label("O servidor revoga a chave e recusa novas mensagens para você neste modo até publicar outra.").classes("text-sm")
        senha = ui.input("Confirme a senha", password=True).mark("excluir-senha")
        apagar = ui.checkbox("Apagar também as chaves privadas deste aparelho (as mensagens antigas ficam ilegíveis)")

        async def confirmar() -> None:
            try:
                await sessao.excluir_chave(modo, senha.value, apagar_privadas=apagar.value)
            except (ErroApi, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            dialogo.close()
            ui.notify("Chave excluída; os contatos foram avisados", type="warning")
            ui.navigate.to("/chaves")

        with ui.row():
            ui.button("Excluir", on_click=confirmar).props("color=negative").mark("excluir-confirmar")
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
    dialogo.open()


def _keystore_local(sessao: Sessao, locais: dict[str, dict]) -> None:
    with secao(
        "Keystore deste aparelho",
        "inventory_2",
        "As privadas guardadas aqui (a real cifrada com a sua senha). Apagar uma é irreversível: "
        "as mensagens cifradas para ela ficam ilegíveis para sempre.",
    ):
        if not locais:
            ui.label("Nenhuma chave privada neste aparelho.").classes("text-sm text-slate-500")
        for key_id, info in sorted(locais.items(), key=lambda kv: kv[1]["criada_em"], reverse=True):
            with ui.row().classes("items-center gap-2 w-full border-b border-slate-100 py-1"):
                selo_modo(info["modo"])
                ui.label(key_id).classes("font-mono text-sm")
                if info["ativa"]:
                    ui.badge("em uso", color="positive")
                ui.label(info["arquivo"]).classes("text-xs text-slate-500")
                ui.space()
                ui.button(icon="delete", on_click=lambda k=key_id, a=info["ativa"]: _dialogo_apagar(sessao, k, a)).props(
                    "flat round dense color=negative"
                ).tooltip("Apagar esta chave privada").mark(f"apagar-{key_id}")


def _dialogo_apagar(sessao: Sessao, key_id: str, ativa: bool) -> None:
    with ui.dialog() as dialogo, ui.card():
        ui.label(f"Apagar a privada {key_id}?").classes("text-lg font-bold")
        ui.label("Simulação “apagar privada”: o que foi cifrado para esta chave não poderá mais ser lido neste aparelho.").classes(
            "text-sm"
        )
        if ativa:
            ui.label(
                "⚠ É a chave em uso: o servidor continua com a pública ativa e os contatos seguirão cifrando para ela. "
                "Troque ou exclua a chave depois."
            ).classes("text-sm text-amber-800")

        def confirmar() -> None:
            sessao.keystore.apagar(key_id)
            dialogo.close()
            ui.notify(f"Privada {key_id} apagada deste aparelho", type="warning")
            ui.navigate.to("/chaves")

        with ui.row():
            ui.button("Apagar", on_click=confirmar).props("color=negative").mark("apagar-confirmar")
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
    dialogo.open()


def _diretorio(sessao: Sessao) -> None:
    with secao("Diretório de chaves públicas", "travel_explore", "O que qualquer usuário autenticado consegue pedir ao servidor."):
        with ui.row().classes("items-end gap-2"):
            usuarios = ui.input("Usuários (separados por vírgula)").classes("w-72")
            modo = ui.select({"real": "real", "didatico": "didático"}, value="real", label="Modo").classes("w-32")
            botao = ui.button("Buscar", icon="search")
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
                publica = carregar_publica(chave.public_key)
                # confere que o key_id anunciado corresponde à chave entregue
                if publica.key_id != chave.key_id:
                    ui.notify(f"A chave de {username} não confere com o key_id anunciado!", type="negative")
                    continue
                with ui.card().classes("w-full bg-slate-50"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"@{username}").classes("font-bold")
                        selo_modo(chave.modo)
                        ui.label(chave.key_id).classes("font-mono text-sm")
                    ui.label(f"Fingerprint {publica.fingerprint_formatado}").classes("font-mono text-xs")
                    numero_seguranca(publica.numero_seguranca)
            if diretorio.sem_chave:
                ui.label(f"Sem chave ativa neste modo: {', '.join(diretorio.sem_chave)}").classes("text-sm text-red-700")

    botao.on_click(buscar)
    usuarios.on("keydown.enter", buscar)
