"""Confidencialidade: o pilar em três provas, uma por seção.

1. A chave sendo criada: um par RSA nasce na tela, número por número (p, q, n, φ, e, d), e ao lado aparece o par
   de verdade deste usuário: a privada no keystore local, cifrada com a senha; a pública no servidor.
2. A chave compartilhada: no RSA o que se compartilha é a chave PÚBLICA. A animação leva as públicas ao diretório
   e de lá ao outro aparelho, enquanto as privadas ficam presas; a tabela confere os fingerprints, e o número de
   segurança da dupla sai igual nos dois aparelhos.
3. Evidências dos dois lados: para uma mensagem, o aparelho de quem envia, o servidor e o aparelho de quem recebe.
   As faixas coloridas (SHA-256 do cifrado e do texto) são as mesmas nas duas telas; no meio só passa cifrado.

As colunas têm a mesma ordem nos dois aparelhos (a dupla em ordem alfabética; quem envia à esquerda), para
comparar as duas telas lado a lado na apresentação.
"""

from __future__ import annotations

import asyncio
import base64
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import confidencialidade as conf
from frontend import inspecao
from frontend.api_client import ErroApi
from frontend.inspecao import Experimento, Percurso
from frontend.key_cache import ChaveSuspeita
from frontend.keystore import ChaveNaoEncontrada
from frontend.mensageiro import ConversaLocal, ItemMensagem, Mensageiro
from frontend.pages.layout import (
    MODO,
    TONS,
    cartao,
    codigo_visual,
    conectar,
    conversas_visiveis,
    encurtar,
    hora,
    icone_destaque,
    mensagens_com_envelope,
    moldura,
    pilula,
    titulo_pagina,
    vazio,
)
from frontend.sessao import Sessao
from shared.crypto import rsa_real
from shared.crypto.chaves import ChavePrivada, carregar_publica
from shared.schemas import Envelope

# ritmo da animação da geração (os testes deixam mais rápido)
QUADROS_EMBARALHAR = 9
INTERVALO_QUADRO = 0.045
PAUSA_PASSO = 0.25

CONTROLE = {i: "·" for i in (*range(32), *range(127, 160))}  # bytes sem caractere visível em latin-1
COR_TEXTO = {"ok": "txt-ok", "erro": "txt-erro", "info": "txt-info", "alerta": "txt-alerta", "neutro": "text-stone-500"}
LEGENDAS_CENA = (
    "① Cada aparelho gera o próprio par e publica só a metade pública no diretório",
    "② O servidor guarda as públicas e entrega a de cada um a quem pedir",
    "③ Cada um recebe a pública do outro e confere o fingerprint; as privadas não saíram do lugar",
)

CSS = """
.cena {position: relative; height: 262px; border-radius: 1rem; overflow: hidden;
  background: linear-gradient(180deg, #fff 0%, #fbf6f1 100%); box-shadow: inset 0 0 0 1px var(--borda)}
.cena .estacao {position: absolute; top: 12px; transform: translateX(-50%); width: 10.5rem;
  display: flex; flex-direction: column; align-items: center; gap: 3px; text-align: center}
.cena .trilho {position: absolute; left: 12%; right: 12%; height: 2px;
  background: repeating-linear-gradient(90deg, #d8ccd2 0 6px, transparent 6px 12px)}
.cena .ficha {position: absolute; transform: translate(-50%, -50%); animation: 9s ease-in-out infinite}
.cena .ida {animation-name: ida}
.cena .volta {animation-name: volta}
@keyframes ida {0%, 6% {left: 12%} 30%, 46% {left: 50%} 72%, 100% {left: 88%}}
@keyframes volta {0%, 6% {left: 88%} 30%, 46% {left: 50%} 72%, 100% {left: 12%}}
.cena .legenda {position: absolute; left: 0; right: 0; bottom: 10px; padding: 0 1rem; text-align: center;
  font-size: .8rem; font-weight: 600; color: var(--tinta); opacity: 0; animation: 9s linear infinite}
.cena .leg1 {animation-name: leg1} .cena .leg2 {animation-name: leg2} .cena .leg3 {animation-name: leg3}
@keyframes leg1 {0%, 29% {opacity: 1} 33%, 100% {opacity: 0}}
@keyframes leg2 {0%, 30% {opacity: 0} 34%, 47% {opacity: 1} 51%, 100% {opacity: 0}}
@keyframes leg3 {0%, 48% {opacity: 0} 52%, 96% {opacity: 1} 100% {opacity: 0}}
.presa {animation: presa 2.2s ease-in-out infinite}
@keyframes presa {0%, 55%, 100% {transform: translateX(0)} 65% {transform: translateX(6px)} 75% {transform: translateX(-4px)} 85% {transform: translateX(2px)}}
.separa-esq {animation: separa-esq .8s cubic-bezier(.2, .8, .2, 1) both}
.separa-dir {animation: separa-dir .8s cubic-bezier(.2, .8, .2, 1) both}
@keyframes separa-esq {from {transform: translateX(45%) scale(.96); opacity: 0} to {transform: none; opacity: 1}}
@keyframes separa-dir {from {transform: translateX(-45%) scale(.96); opacity: 0} to {transform: none; opacity: 1}}
.remoto {border: 2px dashed #d9c8e2; background: #fdfbfe}
.local {box-shadow: 0 0 0 2px #a7e8c2; background: #fff}
.servidor {box-shadow: 0 0 0 1px var(--borda); background: #faf7f4}
.indice:hover {box-shadow: 0 0 0 2px var(--salmao)}
.grade-chaves {display: grid; grid-template-columns: minmax(120px, .8fr) repeat(3, minmax(170px, 1fr)); gap: 6px}
@media (prefers-reduced-motion: reduce) {
  .cena .ficha, .cena .legenda, .presa, .separa-esq, .separa-dir {animation: none}
  .cena .leg3 {opacity: 1}
}
"""


def registrar_paginas(sessao: Sessao, mensageiro: Mensageiro) -> None:
    @ui.page("/confidencialidade")
    async def pagina(mensagem: str | None = None, contato: str | None = None, para: str | None = None):
        if not sessao.logado:
            return RedirectResponse("/login")
        await conectar(mensageiro)
        eu = mensageiro.eu

        itens = mensagens_com_envelope(mensageiro)
        escolhido = next((ci for ci in itens if ci[1].message_id == mensagem), itens[0] if itens else None)
        alvo = None
        if escolhido is not None:
            destinos = _destinatarios(*escolhido) or [eu]
            alvo = para if para in destinos else (eu if eu in destinos else destinos[0])
        contatos = sorted({p for c in conversas_visiveis(mensageiro).values() for p in c.participantes if p != eu})
        if contato not in contatos:
            sugerido = None
            if escolhido is not None:
                sugerido = alvo if escolhido[1].propria else escolhido[1].remetente
            contato = sugerido if sugerido in contatos else (contatos[0] if contatos else None)

        # tudo o que depende do servidor é buscado antes da moldura (ver `conectar`)
        minha = await _minha_chave(sessao)
        dupla = await _dupla(sessao, mensageiro, eu, contato, minha)
        ev = await _evidencias(sessao, mensageiro, *escolhido, alvo, minha) if escolhido is not None else None

        with moldura(sessao, mensageiro, "/confidencialidade") as conteudo:
            ui.add_css(CSS)
            conteudo.classes("max-w-none xl:max-w-[1400px]")
            titulo_pagina(
                "Confidencialidade",
                "Só quem tem a chave privada do destinatário consegue ler a mensagem. Três provas, uma por seção.",
                "lock",
            )
            indice = ui.element("div").classes("w-full grid gap-3 grid-cols-1 md:grid-cols-3")

            corpo, secao1 = _secao(1, "A chave sendo criada", "auto_awesome",
                                   "O par nasce neste aparelho: dois primos secretos viram uma chave pública e uma privada.")
            with corpo:
                _criacao(minha)

            corpo, secao2 = _secao(2, "A chave compartilhada", "share",
                                   "No RSA, o que se compartilha é a chave pública. A privada nunca sai do aparelho do dono.")
            with corpo:
                _compartilhada(dupla, contatos, mensagem)

            corpo, secao3 = _secao(3, "Evidências dos dois lados", "fact_check",
                                   "Uma mensagem vista no aparelho de quem envia, no servidor e no aparelho de quem recebe.")
            with corpo:
                _mostrar_evidencias(ev, itens, eu, contato)

            with indice:
                privada = minha.privada
                _item_indice(1, "A chave sendo criada", secao1, privada is not None,
                             f"{privada.publica.key_id} gerada neste aparelho" if privada else "sem chave privada aqui")
                compartilhada = dupla.contato is not None and dupla.confere_contato and dupla.confere_eu
                _item_indice(2, "A chave compartilhada", secao2, compartilhada,
                             f"públicas conferidas com @{dupla.contato}" if compartilhada
                             else ("comece uma conversa no chat" if dupla.contato is None else "confira os fingerprints"))
                provada = ev is not None and ev.envelope is not None and ev.item.texto is not None
                _item_indice(3, "Evidências dos dois lados", secao3, provada,
                             f"“{encurtar(ev.item.texto, 24)}” só nas pontas" if provada else "envie uma mensagem pelo chat")


# ---------------------------------------------------------------- dados


@dataclass
class MinhaChave:
    privada: ChavePrivada | None
    arquivo: Path | None  # onde a privada está guardada neste aparelho
    primeira_linha: str | None  # cabeçalho do PEM: mostra que está cifrada com a senha
    criada_em: str | None
    fingerprint_servidor: str | None  # da pública ativa que o servidor tem para este usuário


@dataclass
class Dupla:
    eu: str
    contato: str | None
    fp_eu_local: str | None  # calculado da privada deste aparelho
    fp_eu_servidor: str | None  # o que o diretório entrega a quem pede a chave deste usuário
    fp_contato_servidor: str | None
    fp_contato_cache: str | None  # o que este aparelho guardou na primeira conversa

    @property
    def confere_eu(self) -> bool:
        return self.fp_eu_local is not None and self.fp_eu_local == self.fp_eu_servidor

    @property
    def confere_contato(self) -> bool:
        return self.fp_contato_cache is not None and self.fp_contato_cache == self.fp_contato_servidor

    @property
    def fp_contato(self) -> str | None:
        """O fingerprint em que este aparelho confia: o guardado; sem ele, o do diretório."""
        return self.fp_contato_cache or self.fp_contato_servidor


@dataclass
class Evidencias:
    conversa: ConversaLocal
    item: ItemMensagem
    alvo: str
    envelope: Envelope | None  # o envelope de `alvo` (quem envia só o tem na sessão em que enviou)
    fp_alvo: str | None  # fingerprint da chave pública de `alvo` usada na cifra
    arquivo_privada: Path | None  # quando `alvo` sou eu: onde está a privada que abre o envelope
    tentativa: Experimento | None  # quem envia tenta abrir o envelope de `alvo` com a própria privada
    percurso: Percurso | None

    @property
    def resumo_cifrado(self) -> str | None:
        return conf.resumo_cifrado(self.envelope) if self.envelope is not None else None

    @property
    def resumo_texto(self) -> str | None:
        return conf.resumo_texto(self.item.texto) if self.item.texto is not None else None


async def _minha_chave(sessao: Sessao) -> MinhaChave:
    privada = arquivo = primeira = criada = fp_servidor = None
    if sessao.keystore is not None:
        try:
            privada = sessao.keystore.ativa(MODO)
        except ChaveNaoEncontrada:
            privada = None
    if privada is not None:
        info = next((c for c in sessao.keystore.listar() if c["key_id"] == privada.publica.key_id), None)
        if info is not None:
            arquivo = sessao.keystore.pasta / info["arquivo"]
            criada = info["criada_em"]
            if arquivo.exists():
                primeira = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    try:
        ativa = next((c for c in await sessao.api.minhas_chaves() if c.modo == MODO and c.status == "ativa"), None)
        fp_servidor = carregar_publica(ativa.public_key).fingerprint if ativa else None
    except (ErroApi, httpx.HTTPError, ValueError):
        pass
    return MinhaChave(privada, arquivo, primeira, criada, fp_servidor)


async def _dupla(sessao: Sessao, mensageiro: Mensageiro, eu: str, contato: str | None, minha: MinhaChave) -> Dupla:
    """Os fingerprints são recalculados das chaves entregues: não se confia no que o servidor anuncia."""
    dupla = Dupla(eu, contato, minha.privada.publica.fingerprint if minha.privada else None, None, None, None)
    if contato is None:
        dupla.fp_eu_servidor = minha.fingerprint_servidor
        return dupla
    dupla.fp_contato_cache = mensageiro.cache.conhecidas.get((contato, MODO))
    try:
        diretorio = await sessao.api.buscar_chaves([eu, contato], MODO)
    except (ErroApi, httpx.HTTPError):
        dupla.fp_eu_servidor = minha.fingerprint_servidor
        return dupla
    for username, chave in diretorio.chaves.items():
        try:
            fp = carregar_publica(chave.public_key).fingerprint
        except ValueError:
            continue
        if username == eu:
            dupla.fp_eu_servidor = fp
        elif username == contato:
            dupla.fp_contato_servidor = fp
    return dupla


async def _evidencias(
    sessao: Sessao, mensageiro: Mensageiro, conversa: ConversaLocal, item: ItemMensagem, alvo: str, minha: MinhaChave
) -> Evidencias:
    envelope = next((e for e in item.envelopes if e.to == alvo), None)
    fp_alvo = arquivo = tentativa = percurso = None
    if envelope is not None:
        if alvo == mensageiro.eu:
            try:
                privada = sessao.keystore.carregar(envelope.to_key_id)
                fp_alvo = privada.publica.fingerprint
                info = next((c for c in sessao.keystore.listar() if c["key_id"] == envelope.to_key_id), None)
                arquivo = sessao.keystore.pasta / info["arquivo"] if info else None
            except ChaveNaoEncontrada:
                pass
        if fp_alvo is None:
            try:
                fp_alvo = (await mensageiro.cache.por_id(alvo, envelope.to_key_id)).fingerprint
            except (ChaveSuspeita, ErroApi, httpx.HTTPError):
                pass
        if item.propria and alvo != mensageiro.eu and minha.privada is not None:
            tentativa = inspecao.decifrar_com_outra_chave(envelope, minha.privada)
    try:
        percurso = inspecao.percurso(await sessao.api.rastro(item.message_id), alvo)
    except (ErroApi, httpx.HTTPError):
        pass
    return Evidencias(conversa, item, alvo, envelope, fp_alvo, arquivo, tentativa, percurso)


def _destinatarios(conversa: ConversaLocal, item: ItemMensagem) -> list[str]:
    return [p for p in conversa.participantes if p != item.remetente]


def _url(**parametros: str | None) -> str:
    return "/confidencialidade?" + urlencode({k: v for k, v in parametros.items() if v})


# ---------------------------------------------------------------- moldura das seções


def _secao(numero: int, titulo: str, icone: str, descricao: str) -> tuple[ui.column, ui.card]:
    with cartao("w-full p-0 gap-0 overflow-hidden").style("scroll-margin-top: 76px") as caixa:
        with ui.row().classes("w-full items-center gap-3 no-wrap px-5 py-4 border-b border-stone-200 fundo-menta"):
            ui.label(str(numero)).classes(
                "rounded-full bolinha w-9 h-9 flex items-center justify-center text-lg font-bold shrink-0"
            )
            icone_destaque(icone)
            with ui.column().classes("gap-0"):
                ui.label(titulo).classes("text-lg font-bold txt-tinta")
                ui.label(descricao).classes("text-sm text-stone-600")
        corpo = ui.column().classes("w-full gap-4 p-5")
    return corpo, caixa


def _item_indice(numero: int, titulo: str, destino: ui.element, ok: bool, estado: str) -> None:
    with ui.link(target=destino).classes("no-underline"):
        with ui.row().classes("indice clicavel w-full items-center gap-3 no-wrap rounded-2xl p-3 bg-white ring-1 ring-stone-200"):
            ui.label(str(numero)).classes(
                "rounded-full bolinha w-8 h-8 flex items-center justify-center font-bold shrink-0"
            )
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(titulo).classes("font-bold txt-tinta")
                ui.label(estado).classes("text-xs text-stone-500 truncate")
            ui.icon("check_circle" if ok else "radio_button_unchecked", color="positive" if ok else "grey-5").classes("text-2xl")


def _nota(texto: str, icone: str = "info") -> None:
    with ui.row().classes("items-start gap-2 no-wrap"):
        ui.icon(icone, color="grey-6").classes("text-base mt-0.5")
        ui.label(texto).classes("text-sm text-stone-600")


def _prova(icone: str, titulo: str, detalhe: str | None = None, codigo: str | None = None, tom: str = "ok") -> None:
    """Uma linha de evidência: o que foi feito/visto e, quando houver, o código para comparar entre as telas."""
    with ui.row().classes("w-full items-start gap-2 no-wrap"):
        ui.icon(icone).classes(f"text-lg mt-0.5 shrink-0 {COR_TEXTO[tom]}")
        with ui.column().classes("gap-0.5 min-w-0 grow"):
            ui.label(titulo).classes("text-sm font-semibold txt-tinta leading-snug")
            if detalhe:
                ui.label(detalhe).classes("text-xs text-stone-500 quebra")
            if codigo:
                codigo_visual(codigo)


# ---------------------------------------------------------------- 1. a chave sendo criada


@dataclass(frozen=True)
class PassoGeracao:
    simbolo: str
    titulo: str
    explicacao: str
    valor: str
    tipo: str  # secreto / publico / teste
    nota: str = ""


def _criacao(minha: MinhaChave) -> None:
    with ui.row().classes("w-full gap-5 items-start max-lg:flex-wrap"):
        with ui.column().classes("grow basis-0 min-w-80 max-lg:min-w-0 max-lg:w-full gap-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Ver um par nascer").classes("font-bold txt-tinta grow")
                tamanho = ui.toggle({32: "32 bits · contas legíveis", 2048: "2048 bits · tamanho real"}, value=32).props(
                    "dense no-caps unelevated rounded toggle-color=primary"
                ).classes("ring-1 ring-stone-200 rounded-full").mark("conf-tamanho")
            botao = ui.button("Gerar um par agora", icon="auto_awesome").props("unelevated no-caps").mark("conf-gerar")
            palco = ui.column().classes("w-full gap-1.5")
            with palco:
                _nota("Cada número aparece na ordem em que o computador o calcula. É um par de demonstração: a sua chave não muda.")
        with ui.column().classes("w-[26rem] shrink-0 max-lg:w-full gap-3"):
            _sua_chave(minha)

    botao.on_click(lambda: _animar_geracao(palco, botao, int(tamanho.value)))


def _numero(valor: int) -> str:
    texto = str(valor)
    return texto if len(texto) <= 26 else f"{texto[:10]}…{texto[-10:]} ({len(texto)} dígitos)"


def _passos_geracao(g: conf.Geracao) -> list[PassoGeracao]:
    m, c, volta = g.teste
    return [
        PassoGeracao("p", "Sortear o primo p", f"números de {g.bits // 2} bits até um passar no teste de Miller-Rabin",
                     _numero(g.p.valor), "secreto", f"{g.p.candidatos} número(s) sorteado(s)"),
        PassoGeracao("q", "Sortear o primo q", "outro primo, diferente de p", _numero(g.q.valor), "secreto",
                     f"{g.q.candidatos} número(s) sorteado(s)"),
        PassoGeracao("n", "Multiplicar: n = p × q", "fácil de multiplicar; com 2048 bits, ninguém consegue desfazer",
                     _numero(g.n), "publico", f"{g.n.bit_length()} bits"),
        PassoGeracao("φ", "φ(n) = (p − 1) × (q − 1)", "só serve para calcular d e depois é apagado",
                     _numero(g.phi), "secreto"),
        PassoGeracao("e", "Escolher o expoente público e", "65537, sem divisor em comum com φ(n)", str(g.e), "publico",
                     "mdc(e, φ(n)) = 1"),
        PassoGeracao("d", "Calcular o expoente privado: d = e⁻¹ mod φ(n)", "o número que desfaz o que e faz",
                     _numero(g.d), "secreto", f"e × d mod φ(n) = {g.e * g.d % g.phi} ✓"),
        PassoGeracao("✓", f"Testar o par com “{conf.TEXTO_TESTE}”",
                     f"m = {m} → c = mᵉ mod n → cᵈ mod n = {volta}", _numero(c), "teste",
                     "voltou o mesmo número: o par funciona ✓" if volta == m else "não voltou o mesmo número ✗"),
    ]


def _linha_geracao(passo: PassoGeracao) -> ui.label:
    """Uma linha da receita; devolve o rótulo do valor (que a animação embaralha antes de mostrar)."""
    tom, etiqueta, icone = {
        "secreto": ("alerta", "secreto", "visibility_off"),
        "publico": ("info", "público", "public"),
        "teste": ("ok", "teste", "task_alt"),
    }[passo.tipo]
    with ui.row().classes("w-full items-center gap-3 no-wrap rounded-xl px-3 py-2 ring-1 ring-stone-200 bg-white surgir"):
        ui.label(passo.simbolo).classes(
            f"rounded-full w-9 h-9 flex items-center justify-center text-base font-bold font-mono shrink-0 ring-1 {TONS[tom]}"
        )
        with ui.column().classes("gap-0 grow min-w-0"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.label(passo.titulo).classes("font-semibold txt-tinta text-sm")
                pilula(etiqueta, tom, icone)
            ui.label(passo.explicacao).classes("text-xs text-stone-500")
            valor = ui.label(passo.valor).classes("font-mono text-sm txt-tinta break-all")
            if passo.nota:
                ui.label(passo.nota).classes("text-[11px] text-stone-400")
    return valor


def _embaralhado(texto: str) -> str:
    return "".join(random.choice("0123456789") if ch.isdigit() else ch for ch in texto)


async def _animar_geracao(palco: ui.column, botao: ui.button, bits: int) -> None:
    botao.disable()
    try:
        palco.clear()
        with palco:
            with ui.row().classes("items-center gap-2 surgir"):
                ui.spinner(size="sm")
                ui.label(f"Sorteando dois primos de {bits // 2} bits e testando cada um com Miller-Rabin…").classes(
                    "text-sm text-stone-600"
                )
        geracao = await asyncio.to_thread(conf.gerar, bits)
        if palco.is_deleted:
            return
        palco.clear()
        for passo in _passos_geracao(geracao):
            with palco:
                valor = _linha_geracao(passo)
            for _ in range(QUADROS_EMBARALHAR):  # os dígitos "rolam" até o valor calculado
                valor.text = _embaralhado(passo.valor)
                await asyncio.sleep(INTERVALO_QUADRO)
            if palco.is_deleted:
                return
            valor.text = passo.valor
            await asyncio.sleep(PAUSA_PASSO)
        with palco:
            _par_separado(geracao)
    finally:
        if not botao.is_deleted:
            botao.enable()


def _par_separado(g: conf.Geracao) -> None:
    """O par se divide: a metade pública pode ir para o mundo; a privada fica trancada no aparelho."""
    publica = g.publica
    ui.label("O par se divide").classes("rotulo pt-2")
    with ui.row().classes("w-full items-stretch gap-3 no-wrap max-sm:flex-wrap"):
        with ui.column().classes(f"grow basis-0 gap-1 rounded-xl p-3 ring-1 {TONS['info']} separa-esq"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon("key").classes("text-lg")
                ui.label("Chave pública (e, n)").classes("font-bold")
                ui.space()
                pilula("pode ser compartilhada", "info", "share")
            ui.label("Vai para o servidor. Com ela, qualquer um cifra para o dono, mas ninguém decifra.").classes("text-xs")
            ui.label(publica.key_id).classes("font-mono text-xs")
            codigo_visual(publica.fingerprint)
        with ui.column().classes(f"grow basis-0 gap-1 rounded-xl p-3 ring-1 {TONS['marca']} separa-dir"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon("vpn_key").classes("text-lg")
                ui.label("Chave privada (d, n)").classes("font-bold")
                ui.space()
                pilula("nunca sai do aparelho", "ok", "lock")
            ui.label("Fica no keystore, cifrada com a senha. p, q e φ(n) são apagados.").classes("text-xs")
            ui.label(f"d com {g.d.bit_length()} bits").classes("font-mono text-xs")


def _sua_chave(minha: MinhaChave) -> None:
    with ui.column().classes("w-full gap-2 rounded-2xl p-4 ring-1 ring-stone-200 bg-stone-50"):
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            icone_destaque("verified_user", "ok")
            with ui.column().classes("gap-0 grow"):
                ui.label("A sua chave de verdade").classes("font-bold txt-tinta")
                ui.label("gerada assim no seu cadastro, neste aparelho").classes("text-xs text-stone-500")
        privada = minha.privada
        if privada is None:
            _prova("key_off", "Nenhuma chave privada neste aparelho",
                   "Mensagens cifradas para você não podem ser lidas aqui. Publique uma nova em Minhas chaves.", tom="erro")
            return
        publica = privada.publica
        _campo("key_id", publica.key_id)
        if minha.criada_em:
            _campo("criada em", f"{minha.criada_em[8:10]}/{minha.criada_em[5:7]}/{minha.criada_em[:4]} {minha.criada_em[11:16]} (UTC)")
        _campo("tamanho", f"{publica.numeros['n'].bit_length()} bits · e = {publica.numeros['e']}")
        ui.separator().classes("my-1")
        _prova("smartphone", "Privada: só neste aparelho", str(minha.arquivo) if minha.arquivo else None)
        if minha.primeira_linha:
            with ui.row().classes("items-center gap-2 pl-7 flex-wrap"):
                ui.label(minha.primeira_linha).classes("font-mono text-[11px] text-stone-600 bg-white rounded px-1.5 py-0.5 ring-1 ring-stone-200")
                if "ENCRYPTED" in minha.primeira_linha:
                    pilula("cifrada com a sua senha", "ok", "password")
        if minha.fingerprint_servidor == publica.fingerprint:
            _prova("dns", "Pública: o servidor tem exatamente esta", "mesmo fingerprint calculado aqui:", publica.fingerprint)
        elif minha.fingerprint_servidor is None:
            _prova("dns", "O servidor não tem esta pública ativa", "ninguém consegue cifrar para ela", tom="erro")
        else:
            _prova("gpp_bad", "O servidor tem OUTRA pública para você", "fingerprints diferentes", minha.fingerprint_servidor, "erro")


def _campo(rotulo: str, valor: str) -> None:
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label(rotulo).classes("text-xs text-stone-500 w-20 shrink-0")
        ui.label(valor).classes("font-mono text-xs txt-tinta")


# ---------------------------------------------------------------- 2. a chave compartilhada


def _compartilhada(dupla: Dupla, contatos: list[str], mensagem: str | None) -> None:
    with ui.row().classes("w-full items-start gap-3 no-wrap rounded-xl fundo-lima px-4 py-3"):
        ui.icon("lightbulb", color="warning").classes("text-xl mt-0.5")
        ui.label(
            "No RSA os dois não combinam um segredo: a chave compartilhada é a PÚBLICA de cada um. "
            "Com a pública de alguém você só consegue cifrar para essa pessoa; decifrar exige a privada, "
            "que nunca sai do aparelho dela."
        ).classes("text-sm txt-tinta")

    if dupla.contato is None:
        _cena(dupla.eu, "contato", dupla.eu)
        _nota("Comece uma conversa no chat: aqui aparece a conferência das chaves com a outra pessoa.")
        return

    with ui.row().classes("items-center gap-2"):
        ui.label("Conferir com").classes("text-sm text-stone-600")
        ui.select({c: f"@{c}" for c in contatos}, value=dupla.contato,
                   on_change=lambda e: ui.navigate.to(_url(contato=e.value, mensagem=mensagem))).props(
            "dense outlined options-dense"
        ).classes("w-48").mark("conf-contato")
    esquerda, direita = sorted((dupla.eu, dupla.contato))
    _cena(esquerda, direita, dupla.eu)
    _grade_chaves(dupla, esquerda, direita)
    _numero_dupla(dupla)


def _cena(esquerda: str, direita: str, eu: str) -> None:
    """As públicas viajam (aparelho → diretório → outro aparelho); as privadas tremem, mas não saem do lugar."""
    with ui.element("div").classes("cena w-full"):
        for posicao, dono in ((12, esquerda), (88, direita)):
            with ui.element("div").classes("estacao").style(f"left: {posicao}%"):
                with ui.element("div").classes(f"rounded-full p-2.5 flex ring-1 {TONS['marca']}"):
                    ui.icon("smartphone").classes("text-2xl")
                ui.label(f"@{dono}").classes("text-sm font-bold txt-tinta leading-tight")
                ui.label("este aparelho" if dono == eu else "outro aparelho").classes("text-[11px] text-stone-500 leading-tight")
                with ui.row().classes(f"presa items-center gap-1 no-wrap rounded-full px-2 py-0.5 ring-1 {TONS['ok']}"):
                    ui.icon("lock").classes("text-xs")
                    ui.label(f"privada de @{dono} fica aqui").classes("text-[11px] font-semibold whitespace-nowrap")
        with ui.element("div").classes("estacao").style("left: 50%"):
            with ui.element("div").classes(f"rounded-full p-2.5 flex ring-1 {TONS['neutro']}"):
                ui.icon("dns").classes("text-2xl")
            ui.label("Servidor").classes("text-sm font-bold txt-tinta leading-tight")
            ui.label("diretório de chaves públicas").classes("text-[11px] text-stone-500 leading-tight")
            with ui.row().classes(f"items-center gap-1 no-wrap rounded-full px-2 py-0.5 ring-1 {TONS['neutro']}"):
                ui.icon("key_off").classes("text-xs")
                ui.label("nenhuma privada").classes("text-[11px] font-semibold whitespace-nowrap")
        for topo in (158, 198):
            ui.element("div").classes("trilho").style(f"top: {topo}px")
        for classe, dono, topo, final in (("ida", esquerda, 158, 88), ("volta", direita, 198, 12)):
            with ui.row().classes(f"ficha {classe} items-center gap-1 no-wrap rounded-full px-2.5 py-1 ring-1 shadow-sm {TONS['info']}").style(
                f"top: {topo}px; left: {final}%"
            ):
                ui.icon("key").classes("text-sm")
                ui.label(f"pública de @{dono}").classes("text-xs font-semibold whitespace-nowrap")
        for i, legenda in enumerate(LEGENDAS_CENA, start=1):
            ui.label(legenda).classes(f"legenda leg{i}")


def _grade_chaves(dupla: Dupla, esquerda: str, direita: str) -> None:
    """Linhas = chaves; colunas = lugares. A pública aparece nos três; cada privada, só no aparelho do dono."""
    eu, contato = dupla.eu, dupla.contato
    servidor = {eu: dupla.fp_eu_servidor, contato: dupla.fp_contato_servidor}
    neste_aparelho = {eu: dupla.fp_eu_local, contato: dupla.fp_contato_cache}

    def celula_publica(dono: str, lugar: str) -> None:
        if lugar == "servidor":
            fp, conhecido = servidor[dono], neste_aparelho[dono]
            if fp is None:
                _prova("help", "sem chave ativa no diretório", tom="erro")
            elif conhecido is None or fp == conhecido:
                _prova("dns", "entregue pelo diretório", None, fp, "ok" if conhecido else "neutro")
            else:
                _prova("gpp_bad", "DIFERENTE da que este aparelho conhece", "possível troca de chave no caminho", fp, "erro")
        elif lugar == eu:
            fp = neste_aparelho[dono]
            texto = "calculada da privada deste aparelho" if dono == eu else "guardada por este aparelho no 1º contato"
            if fp is None:
                _prova("hourglass_empty", "ainda não guardada" if dono != eu else "sem privada aqui", tom="alerta")
            else:
                _prova("check_circle", texto, None, fp)
        else:
            esperado = servidor[dono]
            texto = "a tela de lá mostra a mesma faixa" if dono == lugar else "lá ela fica guardada no cache"
            _prova("devices", f"na tela de @{lugar}", texto, esperado, "info")

    def celula_privada(dono: str, lugar: str) -> None:
        if lugar == dono:
            _prova("lock", "só aqui" if lugar == eu else "só lá", "no keystore, cifrada com a senha do dono", tom="ok")
        else:
            _prova("block", "não tem", tom="erro")

    with ui.element("div").classes("w-full overflow-x-auto p-1"):
        with ui.element("div").classes("grade-chaves min-w-[720px]"):
            ui.label("")
            for titulo, lugar in ((f"Aparelho de @{esquerda}", esquerda), ("Servidor", "servidor"), (f"Aparelho de @{direita}", direita)):
                with ui.row().classes("items-center gap-1 no-wrap px-2"):
                    ui.icon("dns" if lugar == "servidor" else "smartphone", color="primary").classes("text-base")
                    ui.label(titulo).classes("text-sm font-bold txt-tinta")
                    if lugar == eu:
                        pilula("aqui", "ok")
            linhas = [("pública", d, celula_publica) for d in (esquerda, direita)]
            linhas += [("privada", d, celula_privada) for d in (esquerda, direita)]
            for tipo, dono, celula in linhas:
                with ui.row().classes("items-center gap-1.5 no-wrap px-2"):
                    ui.icon("key" if tipo == "pública" else "vpn_key", color="info" if tipo == "pública" else "positive").classes("text-base")
                    ui.label(f"{tipo.capitalize()} de @{dono}").classes("text-sm font-semibold txt-tinta")
                for lugar in (esquerda, "servidor", direita):
                    classe = "local" if lugar == eu else ("servidor" if lugar == "servidor" else "remoto")
                    with ui.element("div").classes(f"rounded-xl p-2.5 {classe}"):
                        celula(dono, lugar)


def _numero_dupla(dupla: Dupla) -> None:
    if dupla.fp_eu_local is None or dupla.fp_contato is None:
        return
    codigo = conf.codigo_conversa(dupla.fp_eu_local, dupla.fp_contato)
    with ui.column().classes(f"w-full gap-2 rounded-2xl p-4 ring-1 {TONS['marca']}"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.icon("pin").classes("text-xl")
            ui.label(f"Número de segurança de @{dupla.eu} e @{dupla.contato}").classes("font-bold")
        ui.label(
            f"Calculado a partir das duas chaves públicas. Na tela de @{dupla.contato} ele tem de ser idêntico: "
            "se for, ninguém trocou uma chave no caminho (sem homem no meio)."
        ).classes("text-sm")
        with ui.row().classes("gap-1.5 flex-wrap").mark("conf-numero-dupla"):
            for bloco in conf.numero_conversa(dupla.fp_eu_local, dupla.fp_contato).split():
                ui.label(bloco).classes("font-mono text-base font-semibold bg-white/70 rounded-lg px-2 py-0.5")
        codigo_visual(codigo, "lg")


# ---------------------------------------------------------------- 3. evidências dos dois lados


def _mostrar_evidencias(ev: Evidencias | None, itens: list[tuple[ConversaLocal, ItemMensagem]], eu: str, contato: str | None) -> None:
    if ev is None:
        vazio("forum", "Envie uma mensagem pelo chat e volte aqui: cada lado mostra o que tem, e os códigos batem.")
        return
    item, alvo = ev.item, ev.alvo
    destinos = _destinatarios(ev.conversa, item)

    with ui.row().classes("w-full items-center gap-3 flex-wrap"):
        opcoes = {
            i.message_id: f"{'você' if i.propria else '@' + i.remetente} → "
                          f"{', '.join('@' + p for p in _destinatarios(c, i))}: “{encurtar(i.texto or '?', 26)}” · {hora(i.sent_at)}"
            for c, i in itens[:40]
        }
        ui.select(opcoes, value=item.message_id, label="Mensagem",
                  on_change=lambda e: ui.navigate.to(_url(mensagem=e.value, contato=contato))).props(
            "dense outlined options-dense"
        ).classes("min-w-80").mark("conf-mensagem")
        if item.propria and len(destinos) > 1:
            ui.toggle({p: f"@{p}" for p in destinos}, value=alvo,
                      on_change=lambda e: ui.navigate.to(_url(mensagem=item.message_id, para=e.value, contato=contato))).props(
                "dense no-caps unelevated toggle-color=primary"
            )
    outro = alvo if item.propria else item.remetente
    with ui.row().classes("w-full items-start gap-2 no-wrap rounded-xl fundo-pessego px-4 py-3"):
        ui.icon("devices", color="warning").classes("text-xl mt-0.5")
        ui.label(
            f"Para provar: abra o CriptoChat de @{outro} em outra janela, nesta mesma tela e mensagem. As faixas "
            "coloridas dos dois aparelhos ficam iguais, e o texto só aparece nas duas pontas."
        ).classes("text-sm txt-alerta")

    with ui.row().classes("w-full items-stretch gap-2 no-wrap max-xl:flex-wrap"):
        with _coluna(f"Aparelho de @{item.remetente}", "quem envia", item.propria):
            if item.propria:
                _remetente_aqui(ev)
            else:
                _remetente_la(ev)
        _conector()
        with _coluna("Servidor e rede", "só repassa", None):
            _meio(ev)
        _conector()
        with _coluna(f"Aparelho de @{alvo}", "quem recebe", alvo == eu):
            if alvo == eu:
                _destinatario_aqui(ev)
            else:
                _destinatario_la(ev)

    if ev.envelope is not None and item.texto is not None:
        with ui.row().classes("w-full items-start gap-3 no-wrap rounded-xl fundo-menta px-4 py-3 surgir"):
            ui.icon("verified_user", color="positive").classes("text-2xl")
            ui.label(
                f"Conclusão: o texto “{encurtar(item.texto, 60)}” só existe nos aparelhos de @{item.remetente} e @{alvo}. "
                f"No meio passaram só os bytes {ev.resumo_cifrado[:8]}…, e nenhum nó tem a privada de @{alvo} para abri-los."
            ).classes("text-sm txt-ok")


def _coluna(titulo: str, papel: str, local: bool | None) -> ui.column:
    classe = {True: "local", False: "remoto", None: "servidor"}[local]
    with ui.column().classes(f"grow basis-0 min-w-64 max-xl:w-full gap-3 rounded-2xl p-4 {classe}"):
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            icone_destaque("dns" if local is None else "smartphone", "neutro" if local is None else ("ok" if local else "info"), "text-lg")
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(titulo).classes("font-bold txt-tinta truncate")
                ui.label(papel).classes("rotulo")
        if local is True:
            pilula("este aparelho: visto aqui", "ok", "smartphone")
        elif local is False:
            pilula("outro aparelho: confira na tela de lá", "info", "devices")
        else:
            pilula("não tem nenhuma chave privada", "neutro", "key_off")
        corpo = ui.column().classes("w-full gap-3")
    return corpo


def _conector() -> None:
    with ui.column().classes("items-center justify-center gap-1 shrink-0 px-1 max-xl:w-full max-xl:py-1"):
        ui.icon("lock", color="positive").classes("text-base")
        ui.element("div").classes("fluxo w-14 max-xl:rotate-90")
        ui.label("só cifrado").classes("text-[10px] text-stone-400 whitespace-nowrap")


def _sem_envelope(ev: Evidencias) -> None:
    _nota(
        f"O envelope de @{ev.alvo} não ficou neste aparelho (mensagem de uma sessão anterior: quem envia só guarda a "
        "própria cópia). Envie uma nova mensagem para ver as evidências do envio."
    )


def _remetente_aqui(ev: Evidencias) -> None:
    item, envelope, alvo = ev.item, ev.envelope, ev.alvo
    _prova("edit_note", "Escreveu o texto", f"“{item.texto}”" if item.texto is not None else "[ilegível]")
    if envelope is None:
        _sem_envelope(ev)
        return
    _prova("lock", f"Cifrou com a pública de @{alvo}", f"{envelope.to_key_id} · RSA-OAEP · {len(envelope.blocks)} bloco(s)", ev.fp_alvo)
    _prova("send", "Enviou estes bytes cifrados", f"{len(conf.bytes_cifrados(envelope))} bytes · SHA-256:", ev.resumo_cifrado)
    if ev.resumo_texto:
        _prova("fingerprint", "Resumo do texto", "SHA-256 do texto: compara sem mostrar a mensagem", ev.resumo_texto)
    if ev.tentativa is not None:
        recusou = all("inesperado" not in e for e in ev.tentativa.erros)
        _prova(
            "block" if recusou else "warning",
            f"Nem este aparelho abre o envelope de @{alvo}" if recusou else "Este aparelho conseguiu abrir (inesperado)",
            f"tentou com a própria privada: o OAEP recusou os {len(ev.tentativa.erros)} bloco(s)" if recusou else None,
            tom="ok" if recusou else "erro",
        )


def _remetente_la(ev: Evidencias) -> None:
    item, envelope = ev.item, ev.envelope
    _prova("edit_note", "Escreveu o mesmo texto", "lá ele aparece igual", tom="info")
    if envelope is None:
        return
    _prova("lock", "Cifrou com a SUA pública", envelope.to_key_id, ev.fp_alvo, "info")
    _prova("send", "Enviou estes bytes cifrados", "a mesma faixa aparece na tela de lá", ev.resumo_cifrado, "info")
    if ev.resumo_texto:
        _prova("fingerprint", "Mesmo resumo do texto", None, ev.resumo_texto, "info")
    assinatura = item.status == "verificada"
    _prova(
        "draw", f"Assinou com a privada de @{item.remetente}",
        f"{envelope.from_key_id} · " + ("conferida aqui: o cifrado não mudou no caminho" if assinatura else "não conferiu aqui"),
        tom="info" if assinatura else "erro",
    )


def _destinatario_aqui(ev: Evidencias) -> None:
    item, envelope = ev.item, ev.envelope
    if envelope is None:
        _sem_envelope(ev)
        return
    _prova("move_to_inbox", "Recebeu estes bytes cifrados", f"{len(conf.bytes_cifrados(envelope))} bytes · SHA-256:", ev.resumo_cifrado)
    _prova("key", "Cifrados para a chave deste aparelho", envelope.to_key_id, ev.fp_alvo)
    if ev.arquivo_privada is not None:
        _prova("vpn_key", "A privada que abre está aqui", str(ev.arquivo_privada))
    else:
        _prova("key_off", "A privada desta chave não está neste aparelho", "por isso a mensagem não pode ser lida", tom="erro")
    if not item.propria:
        verificada = item.status == "verificada"
        _prova("verified" if verificada else "gpp_bad", f"Conferiu a assinatura de @{item.remetente}" if verificada else "A assinatura não conferiu",
               "nada mudou no caminho" if verificada else item.erro, tom="ok" if verificada else "erro")
    if item.texto is not None:
        _prova("lock_open", "Decifrou o texto", f"“{item.texto}”")
        _prova("fingerprint", "Resumo do texto", "SHA-256 do texto decifrado", ev.resumo_texto)
    else:
        _prova("lock", "Não conseguiu decifrar", item.erro, tom="erro")


def _destinatario_la(ev: Evidencias) -> None:
    envelope, alvo = ev.envelope, ev.alvo
    if envelope is None:
        _sem_envelope(ev)
        return
    _prova("move_to_inbox", "Recebe os mesmos bytes cifrados", "a mesma faixa aparece na tela de lá", ev.resumo_cifrado, "info")
    _prova("vpn_key", f"Abre com a privada {envelope.to_key_id}", f"que só existe no aparelho de @{alvo}", ev.fp_alvo, "info")
    if ev.resumo_texto:
        _prova("lock_open", "Mostra o mesmo texto", "com o mesmo resumo:", ev.resumo_texto, "info")
    p = ev.percurso
    if p is not None and p.confirmado:
        _prova("mark_email_read", f"@{alvo} recebeu e confirmou", "confirmação (ack) registrada pelo servidor")
    elif p is not None and p.status in ("offline", "sem_rota"):
        _prova("schedule", "Ainda na fila do servidor", "chega quando houver caminho até o aparelho de lá", tom="alerta")
    else:
        _prova("schedule", "Sem confirmação ainda", tom="alerta")


def _meio(ev: Evidencias) -> None:
    envelope = ev.envelope
    if envelope is None:
        _prova("visibility_off", "Só viu bytes cifrados", "nenhum texto claro é gravado ou repassado")
        return
    _prova("swap_horiz", "Guarda e repassa os mesmos bytes", "sem alterar nada:", ev.resumo_cifrado, "neutro")
    bruto = conf.bytes_cifrados(envelope)[:40]
    ui.label(bruto.decode("latin-1").translate(CONTROLE)).classes(
        "font-mono text-xs text-stone-600 break-all bg-white rounded-lg px-2 py-1.5 ring-1 ring-stone-200 w-full"
    )
    _prova("visibility", "Vê só os metadados",
           f"@{envelope.from_} → @{envelope.to} · {len(envelope.blocks)} bloco(s) · {hora(envelope.sent_at)}", tom="neutro")
    _prova("visibility_off", "Não vê o texto", "nenhum texto claro é gravado ou repassado")
    _prova("key_off", "Não tem como abrir", "os nós só têm as chaves públicas do diretório")

    resultado = ui.column().classes("w-full gap-1")

    async def tentar() -> None:
        resultado.clear()
        with resultado:
            ui.spinner(size="sm")
        outra = await asyncio.to_thread(rsa_real.gerar)
        experimento = inspecao.decifrar_com_outra_chave(envelope, outra)
        if resultado.is_deleted:
            return
        resultado.clear()
        with resultado:
            with ui.row().classes("items-start gap-2 no-wrap rounded-xl fundo-rosa px-3 py-2 w-full surgir"):
                ui.icon("key_off", color="negative").classes("text-lg mt-0.5")
                with ui.column().classes("gap-0"):
                    ui.label(f"Recusado: sem a privada de @{envelope.to}, nenhum bloco abriu.").classes(
                        "text-sm font-bold txt-erro"
                    ).mark("conf-tentativa")
                    ui.label(f"Tentou com outra chave ({outra.publica.key_id}): {experimento.erros[0]}").classes(
                        "text-xs txt-erro quebra"
                    )

    ui.button(f"Tentar ler sem a privada de @{envelope.to}", icon="lock_person", on_click=tentar).props(
        "outline no-caps color=negative"
    ).classes("w-full").mark("conf-tentar-ler")
