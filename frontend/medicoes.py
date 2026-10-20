"""Medições do Laboratório (RF18): quanto custa gerar, usar e quebrar chaves RSA de cada tamanho.

Rodam em thread (podem levar alguns segundos) e não tocam no keystore: as chaves são descartáveis.
"""

from __future__ import annotations

import math
import secrets
import statistics
import time
from dataclasses import dataclass
from math import gcd

from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.fatoracao import fatorar
from shared.crypto.rsa_didatico import gerar_primo, inverso_modular

TAMANHOS_GERACAO = (64, 512, 1024, 2048)
TAMANHOS_FATORACAO = (16, 24, 32, 40, 48, 56, 64)
E_PADRAO = 65537
MS_POR_ANO = 1000 * 3600 * 24 * 365.25


@dataclass(frozen=True)
class MedicaoChave:
    bits: int
    geracao_ms: float  # implementação própria (Miller-Rabin + Euclides, em Python)
    cifrar_ms: float  # mᵉ mod n
    decifrar_ms: float  # cᵈ mod n
    biblioteca_geracao_ms: float | None  # cryptography (C); só aceita 1024 bits ou mais


def _cronometrar(funcao, *args):
    inicio = time.perf_counter()
    resultado = funcao(*args)
    return resultado, (time.perf_counter() - inicio) * 1000


def _gerar_proprio(bits: int) -> tuple[int, int, int]:
    while True:
        p, q = gerar_primo(bits // 2), gerar_primo(bits - bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and gcd(E_PADRAO, phi) == 1:
            return p * q, E_PADRAO, inverso_modular(E_PADRAO, phi)


def medir_chave(bits: int) -> MedicaoChave:
    (n, e, d), geracao = _cronometrar(_gerar_proprio, bits)
    m = secrets.randbelow(n)
    c, cifrar = _cronometrar(pow, m, e, n)
    volta, decifrar = _cronometrar(pow, c, d, n)
    assert volta == m
    biblioteca = _cronometrar(rsa_real.gerar, bits)[1] if bits >= 1024 else None
    return MedicaoChave(bits, geracao, cifrar, decifrar, biblioteca)


def medir_fatoracao(bits: int, repeticoes: int = 3) -> float:
    """Mediana do tempo (ms) para fatorar n de `bits` bits com Pollard rho."""
    tempos = [fatorar(rsa_didatico.gerar_parametros(bits).n).duracao_ms for _ in range(repeticoes)]
    return statistics.median(tempos)


def log10_tempo_fatoracao(bits_medido: int, ms_medido: float, bits_alvo: int) -> float:
    """Extrapola pelo custo do rho, ~n^(1/4): o tempo dobra a cada 4 bits. Devolve log10 do tempo em ms
    (para 2048 bits o número não cabe num float)."""
    return math.log10(max(ms_medido, 1e-3)) + (bits_alvo - bits_medido) / 4 * math.log10(2)


def formatar_log10_ms(log10_ms: float) -> str:
    if log10_ms < 3:
        return f"{10 ** log10_ms:.1f} ms"
    if log10_ms < math.log10(60_000):
        return f"{10 ** log10_ms / 1000:.1f} s"
    if log10_ms < math.log10(MS_POR_ANO):
        return f"{10 ** log10_ms / 3_600_000:.1f} h"
    anos = log10_ms - math.log10(MS_POR_ANO)
    if anos < 6:
        return f"{10 ** anos:,.0f} anos".replace(",", ".")
    return f"≈ 10^{anos:.0f} anos"
