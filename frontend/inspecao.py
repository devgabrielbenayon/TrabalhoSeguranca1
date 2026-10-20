"""Dados do Inspetor (RF14): rastro local de uma mensagem e os experimentos com o envelope.

O rastro local tem texto claro e, no modo didático, o expoente privado d: nunca sai deste aparelho.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field

from shared.crypto.blocos import decodificar_conteudo
from shared.crypto.chaves import ChavePrivada, ChavePublica
from shared.crypto.envelope import ErroEnvelope, abrir_envelope
from shared.crypto.rsa_didatico import PrivadaDidatica
from shared.schemas import Envelope
from shared.trace import TraceEvent, Tracer

ETAPAS_ENVIO = ("codificacao", "cifragem", "assinatura")
ETAPAS_RECEBIMENTO = ("verificacao", "decifragem", "decodificacao")


@dataclass
class Experimento:
    titulo: str
    linhas: list[dict]
    conclusao: str
    texto_obtido: str | None = None
    erros: list[str] = field(default_factory=list)


def eventos_da_mensagem(tracer: Tracer, message_id: str) -> list[TraceEvent]:
    return [e for e in tracer.eventos if e.message_id == message_id]


def refazer_recebimento(envelope: Envelope, privada: ChavePrivada, publica_remetente: ChavePublica) -> list[TraceEvent]:
    """Verifica e decifra de novo com o rastro ligado (mensagens que vieram do histórico, sem rastro)."""
    tracer = Tracer("inspetor")
    try:
        abrir_envelope(envelope, privada, publica_remetente, tracer=tracer)
    except ErroEnvelope:
        pass  # o evento da etapa que falhou já guarda o erro
    return tracer.eventos


def decifrar_com_outra_chave(envelope: Envelope, outra: ChavePrivada) -> Experimento:
    """Cenário "chave errada": usar o d de outra pessoa. Didático: sai lixo, sem aviso. Real: o OAEP recusa."""
    titulo = f"Decifrar com a chave errada ({outra.publica.key_id})"
    if isinstance(outra, PrivadaDidatica):
        linhas, brutos = [], b""
        for i, bloco_b64 in enumerate(envelope.blocks):
            c = int.from_bytes(base64.b64decode(bloco_b64), "big")
            m = outra.decifrar_int(c % outra.n)  # c pode nem caber em n': a conta é feita mesmo assim
            bloco = (m % (1 << 8 * outra.publica.tamanho_bloco)).to_bytes(outra.publica.tamanho_bloco, "big")
            brutos += bloco
            linhas.append({"bloco": i + 1, "c": c, "m_errado": m, "bytes": bloco.hex()})
        texto = brutos.rstrip(b"\x00").decode("utf-8", errors="replace")
        try:
            decodificar_conteudo(brutos.rstrip(b"\x00"))
            legivel = True
        except ValueError:
            legivel = False
        conclusao = (
            f"cᵈ mod n com d = {outra.d} e n = {outra.n} dá outros números: o resultado é lixo"
            + (" — por acaso ainda é JSON válido." if legivel else ", e nada avisa (RSA de livro não tem padding para detectar).")
        )
        return Experimento(titulo, linhas, conclusao, texto_obtido=texto)

    erros = []
    for i, bloco_b64 in enumerate(envelope.blocks):
        try:
            outra.decifrar_bloco(base64.b64decode(bloco_b64))
            erros.append(f"bloco {i + 1}: decifrou (inesperado)")
        except ValueError as erro:
            erros.append(f"bloco {i + 1}: {erro}")
    return Experimento(
        titulo,
        [{"bloco": i + 1, "resultado": e.split(": ", 1)[1]} for i, e in enumerate(erros)],
        "O OAEP confere a estrutura do bloco depois de decifrar: com a chave errada ele recusa em vez de devolver lixo.",
        erros=erros,
    )


def adulterar_e_verificar(envelope: Envelope, publica_remetente: ChavePublica) -> Experimento:
    """Cenário "assinatura inválida": trocar 1 bit de um bloco em trânsito e verificar de novo."""
    adulterado = envelope.model_copy(deep=True)
    bruto = bytearray(base64.b64decode(adulterado.blocks[0]))
    bruto[-1] ^= 0x01
    adulterado.blocks[0] = base64.b64encode(bytes(bruto)).decode("ascii")
    assinatura = base64.b64decode(envelope.signature)
    linhas = []
    for nome, env in (("original", envelope), ("1 bit trocado no bloco 1", adulterado)):
        dados = env.dados_assinados()
        linhas.append({
            "versao": nome,
            "bloco_1": base64.b64decode(env.blocks[0]).hex(),
            "sha256": hashlib.sha256(dados).hexdigest()[:32] + "…",
            "confere": publica_remetente.verificar(dados, assinatura),
        })
    return Experimento(
        "Adulterar um bloco e verificar a assinatura",
        linhas,
        "Um único bit muda todo o SHA-256 dos dados assinados, e a assinatura deixa de conferir: "
        "o destinatário descarta a mensagem.",
    )
