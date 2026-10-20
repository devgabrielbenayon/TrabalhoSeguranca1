"""Montar e abrir envelopes: cifra com RSA puro por destinatário, assina, verifica e decifra."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from shared.crypto.blocos import codificar_conteudo, decodificar_conteudo, dividir, juntar
from shared.crypto.chaves import ChavePrivada, ChavePublica
from shared.crypto.rsa_didatico import hash_mod_n
from shared.schemas import Envelope
from shared.trace import SEM_RASTREIO, Tracer


class ErroEnvelope(Exception):
    pass


class AssinaturaInvalida(ErroEnvelope):
    pass


class CabecalhoInconsistente(ErroEnvelope):
    pass


class ChaveIncompativel(ErroEnvelope):
    pass


class ConteudoIlegivel(ErroEnvelope):
    pass


@dataclass(frozen=True)
class MensagemAberta:
    message_id: str
    conversation_id: int
    remetente: str
    texto: str
    sent_at: str


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii")


def _numeros(publica: ChavePublica) -> dict:
    """Números públicos da chave para o rastro: e e n no didático; no real, n tem 617 dígitos e basta o tamanho."""
    if publica.modo == "didatico":
        return {"e": publica.e, "n": publica.n}
    return {"e": publica.numeros["e"], "bits_n": publica.numeros["n"].bit_length()}


def _de_b64(texto: str) -> bytes:
    return base64.b64decode(texto, validate=True)


def montar_envelopes(
    texto: str,
    remetente: str,
    privada: ChavePrivada,
    destinatarios: dict[str, ChavePublica],
    conversation_id: int,
    *,
    message_id: str | None = None,
    sent_at: str | None = None,
    incluir_copia: bool = True,
    tracer: Tracer = SEM_RASTREIO,
) -> list[Envelope]:
    """Um envelope por destinatário (+ cópia do remetente), cada um cifrado e assinado."""
    modo = privada.publica.modo
    message_id = message_id or uuid.uuid4().hex
    sent_at = sent_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    alvos = dict(destinatarios)
    if incluir_copia:
        alvos.setdefault(remetente, privada.publica)
    for usuario, publica in alvos.items():
        if publica.modo != modo:
            raise ChaveIncompativel(f"a chave de {usuario} é do modo {publica.modo}, a conversa é {modo}")

    with tracer.etapa("codificacao", entrada=texto, message_id=message_id) as ev:
        conteudo = codificar_conteudo(remetente, message_id, texto)
        ev.saida = conteudo.hex()
        ev.detalhes = {"bytes": len(conteudo), "conteudo": conteudo.decode("utf-8")}

    envelopes = []
    for usuario, publica in alvos.items():
        blocos = dividir(conteudo, publica.tamanho_bloco, completar=publica.blocos_fixos)

        with tracer.etapa("cifragem", entrada={"para": usuario, "key_id": publica.key_id}, message_id=message_id) as ev:
            cifrados, detalhes = [], []
            for bloco in blocos:
                passos = [] if tracer.ativo and modo == "didatico" else None
                cifrado = publica.cifrar_bloco(bloco, passos)
                cifrados.append(cifrado)
                if tracer.ativo:
                    detalhes.append({
                        "bloco_hex": bloco.hex(),
                        "m": int.from_bytes(bloco, "big"),
                        "c": int.from_bytes(cifrado, "big"),
                        "passos": passos,
                    })
            ev.saida = [_b64(c) for c in cifrados]
            ev.detalhes = {"modo": modo, "tamanho_bloco": publica.tamanho_bloco, "blocos": detalhes, **_numeros(publica)}

        envelope = Envelope(
            message_id=message_id,
            conversation_id=conversation_id,
            from_=remetente,
            from_key_id=privada.publica.key_id,
            to=usuario,
            to_key_id=publica.key_id,
            mode=modo,
            sent_at=sent_at,
            blocks=[_b64(c) for c in cifrados],
        )

        with tracer.etapa("assinatura", entrada={"para": usuario}, message_id=message_id) as ev:
            passos = [] if tracer.ativo and modo == "didatico" else None
            dados = envelope.dados_assinados()
            envelope.signature = _b64(privada.assinar(dados, passos))
            ev.saida = envelope.signature
            ev.detalhes = {"passos": passos, "dados_assinados": dados.decode("utf-8"), **_numeros(privada.publica)}
            if tracer.ativo and modo == "didatico":  # s = H(dados)^d mod n, para conferir no Inspetor
                ev.detalhes |= {"h": hash_mod_n(dados, privada.n), "d": privada.d}

        envelopes.append(envelope)
    return envelopes


def abrir_envelope(
    envelope: Envelope,
    privada: ChavePrivada,
    publica_remetente: ChavePublica,
    *,
    tracer: Tracer = SEM_RASTREIO,
) -> MensagemAberta:
    """Verifica a assinatura com a pública do remetente e decifra com a própria privada."""
    if envelope.to_key_id != privada.publica.key_id:
        raise ChaveIncompativel(f"envelope cifrado para {envelope.to_key_id}, chave usada {privada.publica.key_id}")
    if envelope.from_key_id != publica_remetente.key_id:
        raise ChaveIncompativel(
            f"envelope assinado por {envelope.from_key_id}, chave conhecida {publica_remetente.key_id}"
        )

    with tracer.etapa("verificacao", entrada={"de": envelope.from_}, message_id=envelope.message_id) as ev:
        passos = [] if tracer.ativo and envelope.mode == "didatico" else None
        try:
            assinatura = _de_b64(envelope.signature)
        except ValueError as erro:
            raise AssinaturaInvalida("assinatura mal formada") from erro
        dados_assinados = envelope.dados_assinados()
        valida = publica_remetente.verificar(dados_assinados, assinatura, passos)
        ev.saida = valida
        ev.detalhes = {"passos": passos, **_numeros(publica_remetente)}
        if tracer.ativo and envelope.mode == "didatico":  # válida quando s^e mod n == H(dados) mod n
            ev.detalhes |= {"h": hash_mod_n(dados_assinados, publica_remetente.n), "s": int.from_bytes(assinatura, "big")}
        if not valida:
            raise AssinaturaInvalida(f"assinatura de {envelope.from_} não confere")

    with tracer.etapa("decifragem", entrada=envelope.blocks, message_id=envelope.message_id) as ev:
        blocos, detalhes = [], []
        try:
            for bloco_b64 in envelope.blocks:
                passos = [] if tracer.ativo and envelope.mode == "didatico" else None
                cifrado = _de_b64(bloco_b64)
                bloco = privada.decifrar_bloco(cifrado, passos)
                blocos.append(bloco)
                if tracer.ativo:
                    detalhes.append({
                        "c": int.from_bytes(cifrado, "big"),
                        "m": int.from_bytes(bloco, "big"),
                        "bloco_hex": bloco.hex(),
                        "passos": passos,
                    })
        except ValueError as erro:
            raise ConteudoIlegivel(f"falha ao decifrar: {erro}") from erro
        dados = juntar(blocos, remover_preenchimento=privada.publica.blocos_fixos)
        ev.saida = dados.hex()
        ev.detalhes = {"blocos": detalhes, **_numeros(privada.publica)}
        if envelope.mode == "didatico":  # rastro local: d só aparece no Inspetor deste aparelho
            ev.detalhes["d"] = privada.d

    with tracer.etapa("decodificacao", entrada=dados.hex(), message_id=envelope.message_id) as ev:
        try:
            conteudo = decodificar_conteudo(dados)
        except ValueError as erro:
            raise ConteudoIlegivel("o conteúdo decifrado não é uma mensagem válida") from erro
        if conteudo["from"] != envelope.from_ or conteudo["message_id"] != envelope.message_id:
            raise CabecalhoInconsistente(
                f"cabeçalho interno diz {conteudo['from']}/{conteudo['message_id']}, "
                f"envelope diz {envelope.from_}/{envelope.message_id}"
            )
        ev.saida = conteudo["text"]

    return MensagemAberta(
        message_id=envelope.message_id,
        conversation_id=envelope.conversation_id,
        remetente=envelope.from_,
        texto=conteudo["text"],
        sent_at=envelope.sent_at,
    )


def decifrar_capturado(envelope: Envelope, privada: ChavePrivada) -> dict:
    """Só decifra, sem verificar nada: o que um interceptador faz depois de quebrar a chave do destinatário."""
    try:
        blocos = [privada.decifrar_bloco(_de_b64(b)) for b in envelope.blocks]
        return decodificar_conteudo(juntar(blocos, remover_preenchimento=privada.publica.blocos_fixos))
    except ValueError as erro:
        raise ConteudoIlegivel(f"falha ao decifrar: {erro}") from erro
