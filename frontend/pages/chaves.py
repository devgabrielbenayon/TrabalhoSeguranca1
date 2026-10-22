"""Gerenciador de chaves: onde cada metade do par fica (aparelho, servidor, contatos), o par ativo de cada
modo, o ciclo de vida (troca 5.4, exclusão 5.5, "apagar privada") e a busca no diretório de chaves públicas."""

from __future__ import annotations

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend.api_client import ErroApi
from frontend.keystore import ChaveNaoEncontrada
from frontend.mensageiro import Mensageiro
from frontend.pages.layout import (
    ICONE_MODO,
    NOME_CHAVE,
    TOM_MODO,
    TONS,
    avatar,
    cartao,
    conectar,
    icone_destaque,
    mensagem_erro,
    moldura,
    numero_seguranca,
    pilula,
    secao,
    selo_modo,
    titulo_pagina,
)
from frontend.sessao import Sessao
from shared.crypto.base import formatar_fingerprint
from shared.crypto.chaves import carregar_publica
from shared.schemas import ChavePublicaOut

NOME_STATUS = {"ativa": "ativa", "substituida": "substituída", "revogada": "revogada", "local": "não publicada"}
TOM_STATUS = {"ativa": "verde", "substituida": "cinza", "revogada": "vermelho", "local": "ambar"}
DESCRICAO_MODO = {"real": "RSA 2048 bits · OAEP + PSS", "didatico": "RSA de livro, com números pequenos e legíveis"}


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
        contatos = {k: fp for k, fp in mensageiro.cache.conhecidas.items() if k[0] != sessao.usuario.username}
        with moldura(sessao, mensageiro, "/chaves"):
            titulo_pagina(
                "Minhas chaves", "Cada chave é um par: a pública vai para o servidor; a privada nunca sai deste aparelho.", "vpn_key"
            )
            _mapa(publicadas, locais, contatos)
            with ui.row().classes("w-full gap-4 items-stretch max-lg:flex-wrap"):
                for modo in ("real", "didatico"):
                    _cartao_modo(sessao, modo, publicadas, locais)
            _diretorio(sessao)


# ---------------------------------------------------------------- onde cada chave fica


def _mapa(publicadas: list[ChavePublicaOut], locais: dict[str, dict], contatos: dict[tuple[str, str], str]) -> None:
    with secao("Onde cada chave fica", "account_tree", "Você gera o par aqui; só a metade pública viaja."):
        with ui.row().classes("w-full items-stretch gap-2 no-wrap max-xl:flex-wrap"):
            with _lugar("Este aparelho", "smartphone", "teal", "Privadas: decifram o que chega e assinam o que você envia."):
                if not locais:
                    ui.label("nenhuma chave privada").classes("text-sm text-slate-500")
                for key_id, info in sorted(locais.items(), key=lambda kv: kv[1]["criada_em"], reverse=True):
                    with ui.row().classes("items-center gap-1.5 no-wrap"):
                        ui.icon("vpn_key", color="primary" if info["ativa"] else "grey-5").classes("text-base")
                        ui.label(key_id).classes("font-mono text-xs " + ("text-slate-800" if info["ativa"] else "text-slate-400"))
                        selo_modo(info["modo"])
                        if info["ativa"]:
                            ui.label("em uso").classes("text-[11px] font-semibold text-emerald-700")

            _flecha("sobe só a pública", "com prova de posse")

            with _lugar("Servidor", "dns", "cinza", "Diretório de públicas: entrega a sua chave a quem quer falar com você."):
                ativas = [c for c in publicadas if c.status == "ativa"]
                if not ativas:
                    ui.label("nenhuma chave ativa").classes("text-sm text-red-700")
                for chave in ativas:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.icon("key", color="info").classes("text-base")
                        ui.label(chave.key_id).classes("font-mono text-xs text-slate-800")
                        selo_modo(chave.modo)
                antigas = len(publicadas) - len(ativas)
                if antigas:
                    ui.label(f"+ {antigas} antiga(s): substituída(s) ou revogada(s)").classes("text-xs text-slate-500")

            _flecha("cada um busca a do outro", "e confere o key_id")

            with _lugar("Contatos", "group", "azul", "Este aparelho lembra o fingerprint de cada contato e avisa se ele mudar."):
                if not contatos:
                    ui.label("ninguém ainda: o fingerprint é guardado na primeira conversa").classes("text-sm text-slate-500")
                for (username, modo), fingerprint in sorted(contatos.items()):
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        avatar(username, tamanho=6)
                        ui.label(f"@{username}").classes("text-sm font-medium")
                        selo_modo(modo)
                        ui.label(formatar_fingerprint(fingerprint)[:11] + "…").classes("font-mono text-[11px] text-slate-400")


def _lugar(titulo: str, icone: str, tom: str, legenda: str) -> ui.column:
    with ui.column().classes("grow basis-0 min-w-56 max-xl:w-full gap-2 rounded-2xl p-3 ring-1 ring-slate-200 bg-slate-50"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            icone_destaque(icone, tom)
            ui.label(titulo).classes("font-bold text-slate-800")
        ui.label(legenda).classes("text-xs text-slate-500")
        corpo = ui.column().classes("gap-1.5 w-full mt-1")
    return corpo


def _flecha(texto: str, detalhe: str) -> None:
    with ui.column().classes("items-center justify-center gap-0 px-1 shrink-0 max-xl:w-full max-xl:py-1"):
        ui.icon("arrow_forward", color="grey-5").classes("text-3xl max-xl:rotate-90")
        ui.label(texto).classes("text-[11px] font-medium text-slate-600 text-center w-20 max-xl:w-auto leading-tight")
        ui.label(detalhe).classes("text-[10px] text-slate-400 text-center w-20 max-xl:w-auto leading-tight")


# ---------------------------------------------------------------- o par de cada modo


def _cartao_modo(sessao: Sessao, modo: str, publicadas: list[ChavePublicaOut], locais: dict[str, dict]) -> None:
    historico = sorted((c for c in publicadas if c.modo == modo), key=lambda c: c.criada_em)
    ativa = next((c for c in historico if c.status == "ativa"), None)
    privada = None
    if ativa is not None and ativa.key_id in locais:
        try:
            privada = sessao.keystore.carregar(ativa.key_id)
        except ChaveNaoEncontrada:
            privada = None

    with cartao("grow basis-96 p-5 gap-4"):
        with ui.row().classes("items-center gap-3 no-wrap w-full"):
            icone_destaque(ICONE_MODO[modo], TOM_MODO[modo])
            with ui.column().classes("gap-0 grow"):
                ui.label(NOME_CHAVE[modo].capitalize()).classes("text-lg font-bold text-slate-800")
                ui.label(DESCRICAO_MODO[modo]).classes("text-xs text-slate-500")
            if ativa is None:
                pilula("sem chave ativa", "vermelho")

        if ativa is None:
            with ui.row().classes("items-start gap-2 no-wrap rounded-xl bg-red-50 px-3 py-2"):
                ui.icon("key_off", color="negative").classes("mt-0.5")
                ui.label("Ninguém consegue cifrar para você neste modo até você publicar uma nova chave.").classes(
                    "text-sm text-red-800"
                )
        else:
            publica = carregar_publica(ativa.public_key)
            _par(modo, publica, privada, ativa.key_id in locais)
            with ui.expansion("Número de segurança", icon="pin").classes("w-full text-sm -my-2"):
                ui.label("Compare com o que seus contatos veem no aparelho deles.").classes("text-xs text-slate-500")
                numero_seguranca(publica.numero_seguranca)
                ui.label(publica.fingerprint_formatado).classes("font-mono text-[11px] text-slate-400 break-all")

        ui.label("Ciclo de vida").classes("rotulo")
        _ciclo(sessao, modo, historico, locais)

        async def trocar() -> None:
            ui.notify("Gerando o novo par e assinando o desafio do servidor…")
            try:
                saida, _ = await sessao.trocar_chave(modo)
            except (ErroApi, ValueError, httpx.HTTPError) as erro:
                ui.notify(mensagem_erro(erro), type="negative")
                return
            ui.notify(f"Nova chave {saida.key_id} publicada; os contatos foram avisados", type="positive")
            ui.navigate.to("/chaves")

        with ui.row().classes("mt-auto gap-2"):
            ui.button("Trocar chave" if ativa else "Publicar nova chave", icon="autorenew", on_click=trocar).props(
                "unelevated no-caps"
            ).mark(f"trocar-{modo}")
            if ativa:
                ui.button("Excluir chave", icon="delete_forever", on_click=lambda: _dialogo_exclusao(sessao, modo)).props(
                    "outline no-caps color=negative"
                ).mark(f"excluir-{modo}")


def _par(modo: str, publica, privada, privada_aqui: bool) -> None:
    """As duas metades lado a lado: o que cada uma faz e onde fica."""
    with ui.row().classes("w-full gap-3 no-wrap max-sm:flex-wrap"):
        with ui.column().classes(f"grow basis-0 gap-1 rounded-xl p-3 ring-1 {TONS['azul']}"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon("key").classes("text-lg")
                ui.label("Pública").classes("font-bold")
                ui.space()
                pilula("no servidor", "azul", "dns")
            ui.label("cifra para você · confere a sua assinatura").classes("text-xs")
            if modo == "didatico":
                ui.label(f"e = {publica.e}").classes("font-mono text-xs")
                ui.label(f"n = {publica.n} ({publica.n.bit_length()} bits)").classes("font-mono text-xs break-all")
            else:
                ui.label(f"e = {publica.numeros['e']}").classes("font-mono text-xs")
                ui.label(f"n com {publica.numeros['n'].bit_length()} bits").classes("font-mono text-xs")
            ui.label(publica.key_id).classes("font-mono text-[11px] opacity-70")
        tom = "teal" if privada_aqui else "vermelho"
        with ui.column().classes(f"grow basis-0 gap-1 rounded-xl p-3 ring-1 {TONS[tom]}"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon("vpn_key").classes("text-lg")
                ui.label("Privada").classes("font-bold")
                ui.space()
                pilula("só aqui" if privada_aqui else "ausente", tom, "smartphone" if privada_aqui else "warning")
            ui.label("decifra o que chega · assina o que você envia").classes("text-xs")
            if not privada_aqui:
                ui.label("Não está neste aparelho: o que for cifrado para esta chave não poderá ser lido aqui.").classes("text-xs")
            elif modo == "didatico" and privada is not None:
                ui.label(f"d = {privada.d}").classes("font-mono text-xs break-all")
                ui.label("e·d ≡ 1 (mod φ(n))").classes("font-mono text-[11px] opacity-70")
            else:
                ui.label("d guardado cifrado com a sua senha").classes("font-mono text-xs")


def _ciclo(sessao: Sessao, modo: str, historico: list[ChavePublicaOut], locais: dict[str, dict]) -> None:
    """Da chave mais antiga à atual: cada troca substitui a anterior; a exclusão revoga."""
    publicadas = {c.key_id for c in historico}
    itens = [(c.key_id, c.status, c.criada_em.strftime("%d/%m %H:%M")) for c in historico]
    itens += [
        (key_id, "local", info["criada_em"][8:10] + "/" + info["criada_em"][5:7] + " " + info["criada_em"][11:16])
        for key_id, info in sorted(locais.items(), key=lambda kv: kv[1]["criada_em"])
        if info["modo"] == modo and key_id not in publicadas
    ]
    if not itens:
        ui.label("Nenhuma chave neste modo.").classes("text-sm text-slate-500")
        return
    with ui.row().classes("w-full items-stretch gap-1 flex-wrap"):
        for i, (key_id, status, criada) in enumerate(itens):
            if i:
                ui.icon("arrow_forward", color="grey-5").classes("self-center")
            aqui = key_id in locais
            with ui.column().classes(f"gap-0 rounded-xl px-3 py-2 ring-1 {TONS[TOM_STATUS[status]]}").style("min-width: 150px"):
                with ui.row().classes("items-center gap-1 no-wrap w-full"):
                    ui.icon("vpn_key" if aqui else "key_off").classes("text-sm")
                    ui.label(NOME_STATUS[status]).classes("text-sm font-bold grow")
                    if aqui:
                        ui.button(
                            icon="delete", on_click=lambda k=key_id: _dialogo_apagar(sessao, k, bool(locais[k]["ativa"]))
                        ).props("flat round dense size=sm color=negative").tooltip("Apagar a chave privada deste aparelho").mark(
                            f"apagar-{key_id}"
                        )
                ui.label(key_id).classes("font-mono text-xs")
                ui.label(f"{NOME_STATUS[status]} · {'privada neste aparelho' if aqui else 'privada ausente'}").classes(
                    "text-[11px] opacity-80"
                )
                ui.label(f"criada {criada}").classes("text-[11px] opacity-60")


def _dialogo_exclusao(sessao: Sessao, modo: str) -> None:
    with ui.dialog() as dialogo, cartao("p-5 gap-3 max-w-md"):
        ui.label(f"Excluir a {NOME_CHAVE[modo]}").classes("text-lg font-bold")
        ui.label("O servidor revoga a chave e recusa novas mensagens para você neste modo até publicar outra.").classes("text-sm")
        senha = ui.input("Confirme a senha", password=True).props("outlined dense").classes("w-full").mark("excluir-senha")
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

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat no-caps")
            ui.button("Excluir", on_click=confirmar).props("unelevated no-caps color=negative").mark("excluir-confirmar")
    dialogo.open()


def _dialogo_apagar(sessao: Sessao, key_id: str, ativa: bool) -> None:
    with ui.dialog() as dialogo, cartao("p-5 gap-3 max-w-md"):
        ui.label(f"Apagar a privada {key_id}?").classes("text-lg font-bold")
        ui.label("O que foi cifrado para esta chave não poderá mais ser lido neste aparelho.").classes("text-sm")
        if ativa:
            ui.label(
                "É a chave em uso: o servidor continua com a pública ativa e os contatos seguirão cifrando para ela. "
                "Troque ou exclua a chave depois."
            ).classes("text-sm text-amber-800 bg-amber-50 rounded-lg px-3 py-2")

        def confirmar() -> None:
            sessao.keystore.apagar(key_id)
            dialogo.close()
            ui.notify(f"Privada {key_id} apagada deste aparelho", type="warning")
            ui.navigate.to("/chaves")

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat no-caps")
            ui.button("Apagar", on_click=confirmar).props("unelevated no-caps color=negative").mark("apagar-confirmar")
    dialogo.open()


# ---------------------------------------------------------------- diretório


def _diretorio(sessao: Sessao) -> None:
    with cartao("w-full p-0"):
        with ui.expansion(
            "Consultar o diretório de chaves públicas", caption="O que qualquer usuário autenticado consegue pedir ao servidor.",
            icon="travel_explore",
        ).classes("w-full"):
            with ui.row().classes("items-end gap-2"):
                usuarios = ui.input("Usuários (separados por vírgula)").props("outlined dense").classes("w-72")
                modo = ui.select({"real": "real", "didatico": "didático"}, value="real", label="Modo").props("outlined dense").classes(
                    "w-32"
                )
                botao = ui.button("Buscar", icon="search").props("unelevated no-caps")
            resultado = ui.column().classes("w-full gap-2 pt-2")

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
                with ui.column().classes("w-full gap-1 rounded-xl ring-1 ring-slate-200 bg-slate-50 p-3"):
                    with ui.row().classes("items-center gap-2"):
                        avatar(username, tamanho=7)
                        ui.label(f"@{username}").classes("font-bold")
                        selo_modo(chave.modo)
                        ui.label(chave.key_id).classes("font-mono text-xs text-slate-500")
                    numero_seguranca(publica.numero_seguranca)
                    ui.label(publica.fingerprint_formatado).classes("font-mono text-[11px] text-slate-400")
            if diretorio.sem_chave:
                ui.label(f"Sem chave ativa neste modo: {', '.join(diretorio.sem_chave)}").classes("text-sm text-red-700")

    botao.on_click(buscar)
    usuarios.on("keydown.enter", buscar)
