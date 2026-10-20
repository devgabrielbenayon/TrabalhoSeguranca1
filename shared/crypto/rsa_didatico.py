"""RSA implementado do zero (modo didático): números pequenos e legíveis, sem padding.

Inseguro por construção (RSA "de livro", chaves de 16 a 64 bits). Existe para que cada
número — p, q, n, φ, e, d, m, c — apareça no Inspetor e possa ser conferido à mão.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from math import gcd

from shared.crypto.base import IdentidadeChave

RODADAS_MILLER_RABIN = 40
EXPOENTES_CANDIDATOS = (65537, 257, 17, 5, 3)
BITS_MIN, BITS_MAX = 16, 64
PRIMOS_PEQUENOS = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


# ---------------------------------------------------------------- aritmética


def egcd(a: int, b: int) -> tuple[int, int, int]:
    """Euclides estendido (iterativo): devolve (g, x, y) com a·x + b·y = g = mdc(a, b)."""
    x0, x1, y0, y1 = 1, 0, 0, 1
    while b:
        q, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - q * x1
        y0, y1 = y1, y0 - q * y1
    return a, x0, y0


def inverso_modular(e: int, phi: int) -> int:
    g, x, _ = egcd(e, phi)
    if g != 1:
        raise ValueError(f"e={e} e φ={phi} não são coprimos")
    return x % phi


def eh_primo(n: int, rodadas: int = RODADAS_MILLER_RABIN) -> bool:
    """Teste de Miller-Rabin (probabilístico; erro ≤ 4^-rodadas)."""
    if n < 2:
        return False
    for p in PRIMOS_PEQUENOS:
        if n % p == 0:
            return n == p
    r, d = 0, n - 1
    while d % 2 == 0:
        r, d = r + 1, d // 2
    for _ in range(rodadas):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def gerar_primo(bits: int) -> int:
    """Primo com exatamente `bits` bits (os dois bits mais altos ligados garantem o tamanho de n)."""
    while True:
        candidato = secrets.randbits(bits) | (0b11 << (bits - 2)) | 1
        if eh_primo(candidato):
            return candidato


def pow_mod_trace(base: int, exp: int, mod: int, passos: list[dict] | None = None) -> int:
    """Exponenciação modular por square-and-multiply.

    Se `passos` for uma lista, recebe uma linha por bit do expoente (tabela do Inspetor).
    """
    if not 0 <= base < mod:
        raise ValueError(f"a base {base} precisa estar em [0, {mod})")
    resultado = 1
    for bit in bin(exp)[2:]:
        resultado = (resultado * resultado) % mod
        passo = {"bit": bit, "quadrado": resultado}
        if bit == "1":
            resultado = (resultado * base) % mod
            passo["multiplica"] = resultado
        if passos is not None:
            passos.append(passo)
    return resultado


# ---------------------------------------------------------------- geração


@dataclass(frozen=True)
class GeracaoDidatica:
    """Todos os números da geração, para a animação do Passo 0. p, q e φ não vão para a chave."""

    p: int
    q: int
    n: int
    phi: int
    e: int
    d: int

    def privada(self) -> PrivadaDidatica:
        return PrivadaDidatica(self.d, PublicaDidatica(self.e, self.n))


def _escolher_e(phi: int) -> int | None:
    for e in EXPOENTES_CANDIDATOS:
        if e < phi and gcd(e, phi) == 1:
            return e
    return None


def gerar_parametros(
    bits: int = 32, p: int | None = None, q: int | None = None, e: int | None = None
) -> GeracaoDidatica:
    """Gera (p, q, n, φ, e, d). Com p e q informados, usa-os (ex.: 61 e 53 do exemplo clássico)."""
    if (p is None) != (q is None):
        raise ValueError("informe p e q juntos")
    if p is not None:
        if not (eh_primo(p) and eh_primo(q)) or p == q:
            raise ValueError("p e q precisam ser primos distintos")
        phi = (p - 1) * (q - 1)
        e = e if e is not None else _escolher_e(phi)
        if e is None or gcd(e, phi) != 1:
            raise ValueError(f"e={e} não é coprimo com φ={phi}")
        n = p * q
        if n <= 255:
            raise ValueError("n precisa ser > 255 para cifrar ao menos 1 byte por bloco")
        return GeracaoDidatica(p, q, n, phi, e, inverso_modular(e, phi))

    if not BITS_MIN <= bits <= BITS_MAX:
        raise ValueError(f"o modo didático usa n de {BITS_MIN} a {BITS_MAX} bits")
    bits_p = bits // 2
    while True:
        p, q = gerar_primo(bits_p), gerar_primo(bits - bits_p)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        e_escolhido = e if e is not None else _escolher_e(phi)
        # e fixo pode não ser coprimo com este φ: nesse caso sorteia outros primos
        if e_escolhido is None or e_escolhido >= phi or gcd(e_escolhido, phi) != 1:
            continue
        return GeracaoDidatica(p, q, p * q, phi, e_escolhido, inverso_modular(e_escolhido, phi))


# ---------------------------------------------------------------- chaves


def hash_mod_n(dados: bytes, n: int) -> int:
    # n pequeno trunca o hash: limitação proposital do modo didático
    return int.from_bytes(hashlib.sha256(dados).digest(), "big") % n


class PublicaDidatica(IdentidadeChave):
    modo = "didatico"
    blocos_fixos = True  # sem padding: blocos completados com zeros e decifrados no tamanho fixo

    def __init__(self, e: int, n: int) -> None:
        self.e, self.n = e, n

    @property
    def tamanho_bloco(self) -> int:
        return max(1, (self.n.bit_length() - 1) // 8)

    @property
    def tamanho_cifrado(self) -> int:
        return (self.n.bit_length() + 7) // 8

    @property
    def numeros(self) -> dict[str, int]:
        return {"e": self.e, "n": self.n}

    def bytes_canonicos(self) -> bytes:
        return self.exportar().encode()

    def exportar(self) -> str:
        return json.dumps({"modo": self.modo, "e": self.e, "n": self.n}, sort_keys=True, separators=(",", ":"))

    def cifrar_int(self, m: int, passos: list[dict] | None = None) -> int:
        return pow_mod_trace(m, self.e, self.n, passos)

    def cifrar_bloco(self, bloco: bytes, passos: list[dict] | None = None) -> bytes:
        if len(bloco) > self.tamanho_bloco:
            raise ValueError(f"bloco de {len(bloco)} bytes excede o máximo de {self.tamanho_bloco}")
        c = self.cifrar_int(int.from_bytes(bloco, "big"), passos)
        return c.to_bytes(self.tamanho_cifrado, "big")

    def verificar(self, dados: bytes, assinatura: bytes, passos: list[dict] | None = None) -> bool:
        s = int.from_bytes(assinatura, "big")
        if s >= self.n:
            return False
        return pow_mod_trace(s, self.e, self.n, passos) == hash_mod_n(dados, self.n)


class PrivadaDidatica:
    modo = "didatico"

    def __init__(self, d: int, publica: PublicaDidatica) -> None:
        self.d, self.publica = d, publica

    @property
    def n(self) -> int:
        return self.publica.n

    def decifrar_int(self, c: int, passos: list[dict] | None = None) -> int:
        return pow_mod_trace(c, self.d, self.n, passos)

    def decifrar_bloco(self, cifrado: bytes, passos: list[dict] | None = None) -> bytes:
        c = int.from_bytes(cifrado, "big")
        if c >= self.n:
            raise ValueError("bloco cifrado maior que n")
        m = self.decifrar_int(c, passos)
        tamanho = self.publica.tamanho_bloco
        # com a chave errada m pode não caber no bloco: o resultado é lixo, como deve ser
        return (m % (1 << (8 * tamanho))).to_bytes(tamanho, "big")

    def assinar(self, dados: bytes, passos: list[dict] | None = None) -> bytes:
        s = pow_mod_trace(hash_mod_n(dados, self.n), self.d, self.n, passos)
        return s.to_bytes(self.publica.tamanho_cifrado, "big")

    def exportar(self) -> str:
        """Serialização local para o keystore. Nunca é enviada ao servidor."""
        return json.dumps({"modo": self.modo, "d": self.d, "e": self.publica.e, "n": self.n})

    @classmethod
    def carregar(cls, texto: str) -> PrivadaDidatica:
        dados = json.loads(texto)
        return cls(dados["d"], PublicaDidatica(dados["e"], dados["n"]))


def gerar(bits: int = 32) -> PrivadaDidatica:
    return gerar_parametros(bits).privada()
