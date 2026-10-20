"""Quebrar uma chave RSA pequena (RF18): fatorar n e recalcular d só com a chave pública.

Pollard rho na variante de Brent: o número de passos cresce com √p ≈ n^(1/4), então cada 8 bits a mais
em n multiplicam o tempo por ~4. Com 64 bits leva milissegundos; com 2048 bits, 2^512 passos —
inviável (ataques reais usam o crivo de corpos numéricos, e mesmo assim o recorde público é de 829 bits).
"""

from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass

from shared.crypto.rsa_didatico import PrivadaDidatica, PublicaDidatica, eh_primo, inverso_modular

PRIMOS_TENTATIVA = 1000  # divisão por tentativa antes do rho: tira fatores pequenos de graça
LIMITE_PASSOS = 50_000_000


class FatoracaoFalhou(Exception):
    pass


@dataclass(frozen=True)
class Fatoracao:
    n: int
    p: int
    q: int
    metodo: str
    passos: int
    duracao_ms: float


@dataclass(frozen=True)
class ChaveQuebrada:
    fatoracao: Fatoracao
    phi: int
    e: int
    d: int

    def privada(self) -> PrivadaDidatica:
        return PrivadaDidatica(self.d, PublicaDidatica(self.e, self.fatoracao.n))


def fatorar(n: int, limite_passos: int = LIMITE_PASSOS) -> Fatoracao:
    """Encontra p ≤ q com p·q = n (n produto de dois primos, como num módulo RSA)."""
    if n < 4:
        raise ValueError("n precisa ser composto e maior que 3")
    inicio = time.perf_counter()
    for p in range(2, PRIMOS_TENTATIVA):
        if n % p == 0:
            return _resultado(n, p, "divisão por tentativa", p - 1, inicio)
    if eh_primo(n):
        raise FatoracaoFalhou(f"{n} é primo: não é um módulo RSA")
    passos = 0
    while passos < limite_passos:  # cada tentativa usa outra função pseudoaleatória
        fator, gastos = _brent(n, limite_passos - passos)
        passos += gastos
        if fator is not None and fator != n:
            return _resultado(n, fator, "Pollard rho (Brent)", passos, inicio)
    raise FatoracaoFalhou(f"desisti depois de {passos} passos")


def quebrar(publica: PublicaDidatica, limite_passos: int = LIMITE_PASSOS) -> ChaveQuebrada:
    """Da chave pública (e, n) até a privada d: fatora n, calcula φ(n) e inverte e."""
    fatoracao = fatorar(publica.n, limite_passos)
    phi = (fatoracao.p - 1) * (fatoracao.q - 1)
    return ChaveQuebrada(fatoracao, phi, publica.e, inverso_modular(publica.e, phi))


def _resultado(n: int, fator: int, metodo: str, passos: int, inicio: float) -> Fatoracao:
    p, q = sorted((fator, n // fator))
    return Fatoracao(n, p, q, metodo, passos, (time.perf_counter() - inicio) * 1000)


def _brent(n: int, limite: int) -> tuple[int | None, int]:
    """Uma rodada de Pollard–Brent com x² + c. Devolve (fator ou None, passos gastos)."""
    y, c, m = secrets.randbelow(n - 1) + 1, secrets.randbelow(n - 1) + 1, 128
    g, r, q, passos = 1, 1, 1, 0
    x = ys = y
    while g == 1:
        x = y
        for _ in range(r):
            y = (y * y + c) % n
        k = 0
        while k < r and g == 1:
            ys = y
            for _ in range(min(m, r - k)):
                y = (y * y + c) % n
                q = q * abs(x - y) % n
            g = math.gcd(q, n)
            k += m
        passos += r
        r *= 2
        if passos > limite:
            return None, passos
    if g == n:  # o produto acumulado passou do ponto: refaz passo a passo a partir de ys
        while True:
            ys = (ys * ys + c) % n
            g = math.gcd(abs(x - ys), n)
            if g > 1:
                break
    return (g if g != n else None), passos
