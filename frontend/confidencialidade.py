"""Dados da tela Confidencialidade: um par RSA gerado número por número e os códigos comparáveis entre aparelhos.

Os códigos (SHA-256 dos bytes cifrados, do texto e das chaves públicas) saem iguais nos dois aparelhos de
uma conversa: é a evidência de que os dois lados têm o mesmo cifrado, a mesma mensagem e as mesmas chaves,
sem que nenhum deles precise mostrar a própria chave privada.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from math import gcd

from cryptography.hazmat.primitives.asymmetric import rsa

from shared.crypto.base import numero_seguranca
from shared.crypto.chaves import ChavePublica
from shared.crypto.rsa_didatico import PublicaDidatica, eh_primo
from shared.crypto.rsa_real import EXPOENTE_PUBLICO, PublicaReal
from shared.schemas import Envelope

TEXTO_TESTE = "oi"  # cifrado e decifrado com o par recém-gerado, para mostrar que ele funciona


@dataclass(frozen=True)
class Primo:
    valor: int
    candidatos: int  # quantos números foram sorteados até um passar no Miller-Rabin


@dataclass(frozen=True)
class Geracao:
    """Todos os números de um par RSA. p, q, φ e d são secretos; n e e formam a chave pública."""

    bits: int
    p: Primo
    q: Primo
    e: int
    sorteios: int  # pares (p, q) sorteados até e ser coprimo com φ(n)

    @property
    def n(self) -> int:
        return self.p.valor * self.q.valor

    @property
    def phi(self) -> int:
        return (self.p.valor - 1) * (self.q.valor - 1)

    @property
    def d(self) -> int:
        return pow(self.e, -1, self.phi)

    @property
    def publica(self) -> ChavePublica:
        if self.bits >= 512:
            return PublicaReal(rsa.RSAPublicNumbers(self.e, self.n).public_key())
        return PublicaDidatica(self.e, self.n)

    @property
    def teste(self) -> tuple[int, int, int]:
        """(m, c, m decifrado) para o texto de teste: m → c = mᵉ mod n → cᵈ mod n."""
        m = int.from_bytes(TEXTO_TESTE.encode(), "big")
        c = pow(m, self.e, self.n)
        return m, c, pow(c, self.d, self.n)


def sortear_primo(bits: int) -> Primo:
    """Sorteia números de `bits` bits (os dois mais altos ligados, para n ter o tamanho certo) até achar um primo."""
    candidatos = 0
    while True:
        candidatos += 1
        candidato = secrets.randbits(bits) | (0b11 << (bits - 2)) | 1
        if eh_primo(candidato):
            return Primo(candidato, candidatos)


def gerar(bits: int, e: int = EXPOENTE_PUBLICO) -> Geracao:
    """Um par com `bits` bits: 32 para ler as contas, 2048 para o tamanho real (leva menos de um segundo)."""
    metade = bits // 2
    sorteios = 0
    while True:
        sorteios += 1
        p, q = sortear_primo(metade), sortear_primo(bits - metade)
        if p.valor != q.valor and e < (p.valor - 1) * (q.valor - 1) and gcd(e, (p.valor - 1) * (q.valor - 1)) == 1:
            return Geracao(bits, p, q, e, sorteios)


# ---------------------------------------------------------------- códigos comparáveis entre aparelhos


def resumo(dados: bytes) -> str:
    """SHA-256 em hexadecimal."""
    return hashlib.sha256(dados).hexdigest()


def bytes_cifrados(envelope: Envelope) -> bytes:
    """Os blocos do envelope, como passam pela rede."""
    return b"".join(base64.b64decode(b) for b in envelope.blocks)


def resumo_cifrado(envelope: Envelope) -> str:
    return resumo(bytes_cifrados(envelope))


def resumo_texto(texto: str) -> str:
    return resumo(texto.encode("utf-8"))


def codigo_conversa(fingerprint_a: str, fingerprint_b: str) -> str:
    """SHA-256 das duas públicas em ordem fixa: não depende de quem calcula, então os dois aparelhos chegam ao mesmo."""
    return resumo("".join(sorted((fingerprint_a, fingerprint_b))).encode("ascii"))


def numero_conversa(fingerprint_a: str, fingerprint_b: str) -> str:
    """Número de segurança da dupla, em 12 blocos de 5 dígitos."""
    return numero_seguranca(codigo_conversa(fingerprint_a, fingerprint_b))
