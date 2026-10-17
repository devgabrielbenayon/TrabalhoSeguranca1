"""Identidade de uma chave pública, comum aos dois modos: fingerprint, key_id e número de segurança."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from functools import cached_property


def formatar_fingerprint(fingerprint: str) -> str:
    """Ex.: A1:9F:03:C2:… (16 primeiros bytes de um SHA-256 em hexadecimal)."""
    return ":".join(fingerprint[i : i + 2] for i in range(0, 32, 2)).upper()


class IdentidadeChave(ABC):
    @abstractmethod
    def bytes_canonicos(self) -> bytes:
        """Serialização determinística da chave pública (base do fingerprint)."""

    @cached_property
    def fingerprint(self) -> str:
        """SHA-256 da chave pública, em hexadecimal."""
        return hashlib.sha256(self.bytes_canonicos()).hexdigest()

    @property
    def key_id(self) -> str:
        return "k_" + self.fingerprint[:16]

    @property
    def fingerprint_formatado(self) -> str:
        return formatar_fingerprint(self.fingerprint)

    @property
    def numero_seguranca(self) -> str:
        """60 dígitos em 12 blocos de 5, para comparar fora do app (estilo Signal)."""
        digitos = str(int(self.fingerprint, 16)).zfill(78)[:60]
        return " ".join(digitos[i : i + 5] for i in range(0, 60, 5))
