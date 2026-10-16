"""Interface comum aos dois modos e funções para gerar/carregar chaves sem saber o modo."""

from __future__ import annotations

import json
from typing import Literal, Union

from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.rsa_didatico import PrivadaDidatica, PublicaDidatica
from shared.crypto.rsa_real import PrivadaReal, PublicaReal

Modo = Literal["didatico", "real"]
ChavePublica = Union[PublicaDidatica, PublicaReal]
ChavePrivada = Union[PrivadaDidatica, PrivadaReal]


def gerar_par(modo: Modo, bits: int | None = None) -> ChavePrivada:
    if modo == "didatico":
        return rsa_didatico.gerar(bits or 32)
    if modo == "real":
        return rsa_real.gerar(bits or rsa_real.BITS_PADRAO)
    raise ValueError(f"modo desconhecido: {modo}")


def carregar_publica(texto: str) -> ChavePublica:
    """Reconstrói a chave pública a partir de `exportar()` (JSON no didático, PEM no real)."""
    texto = texto.strip()
    if texto.startswith("-----BEGIN"):
        return PublicaReal.carregar(texto)
    dados = json.loads(texto)
    if dados.get("modo") != "didatico":
        raise ValueError("formato de chave pública desconhecido")
    return PublicaDidatica(int(dados["e"]), int(dados["n"]))
