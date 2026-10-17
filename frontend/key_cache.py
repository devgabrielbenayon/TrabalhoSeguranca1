"""Cache das chaves públicas dos contatos (passo 1: não pedir a chave a cada mensagem).

Toda chave recebida do servidor é conferida: o key_id anunciado tem de ser o da chave entregue.
`conhecidas` guarda o último fingerprint visto de cada contato; quando ele muda, `ao_mudar` é chamado
(o Mensageiro mostra o alerta "a chave de X mudou" e persiste o novo fingerprint no keystore).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from frontend.api_client import ApiCliente
from shared.crypto.chaves import ChavePublica, carregar_publica
from shared.schemas import ChavePublicaOut, Modo

# (username, modo, fingerprint anterior ou None se é o primeiro, fingerprint novo)
AoMudar = Callable[[str, str, str | None, str], None]


class SemChave(Exception):
    def __init__(self, usuarios: list[str]) -> None:
        super().__init__(f"sem chave ativa: {', '.join(usuarios)}")
        self.usuarios = usuarios


class ChaveSuspeita(Exception):
    """O servidor entregou uma chave que não corresponde ao key_id/usuário anunciado."""


@dataclass
class CacheChaves:
    api: ApiCliente
    conhecidas: dict[tuple[str, str], str] = field(default_factory=dict)  # (username, modo) → fingerprint
    ao_mudar: AoMudar | None = None
    _ativas: dict[tuple[str, str], ChavePublica] = field(default_factory=dict)  # (username, modo) → chave
    _por_id: dict[str, tuple[str, ChavePublica]] = field(default_factory=dict)  # key_id → (username, chave)
    buscas: int = 0  # quantas vezes foi ao servidor (o Inspetor mostra o efeito do cache)

    async def obter(self, usuarios: list[str], modo: Modo) -> dict[str, ChavePublica]:
        faltando = [u for u in usuarios if (u, modo) not in self._ativas]
        if faltando:
            self.buscas += 1
            diretorio = await self.api.buscar_chaves(faltando, modo)
            if diretorio.sem_chave:
                raise SemChave(diretorio.sem_chave)
            for username, chave in diretorio.chaves.items():
                self.guardar(username, chave)
        return {u: self._ativas[(u, modo)] for u in usuarios}

    async def por_id(self, username: str, key_id: str) -> ChavePublica:
        """Chave de um key_id específico (ex.: verificar mensagem assinada com uma chave já trocada)."""
        if key_id in self._por_id:
            dono, chave = self._por_id[key_id]
        else:
            self.buscas += 1
            saida = await self.api.chave_por_id(key_id)
            chave = self._conferir(saida)
            dono = saida.username
            self._por_id[key_id] = (dono, chave)
        if dono != username:
            raise ChaveSuspeita(f"a chave {key_id} pertence a {dono}, não a {username}")
        return chave

    def guardar(self, username: str, saida: ChavePublicaOut) -> ChavePublica:
        if saida.username != username:
            raise ChaveSuspeita(f"pedi a chave de {username} e recebi a de {saida.username}")
        chave = self._conferir(saida)
        if saida.status == "ativa":
            self._ativas[(username, saida.modo)] = chave
            self.registrar_fingerprint(username, saida.modo, chave.fingerprint)
        self._por_id[chave.key_id] = (username, chave)
        return chave

    def registrar_fingerprint(self, username: str, modo: str, fingerprint: str) -> None:
        anterior = self.conhecidas.get((username, modo))
        if anterior == fingerprint:
            return
        self.conhecidas[(username, modo)] = fingerprint
        if self.ao_mudar is not None:
            self.ao_mudar(username, modo, anterior, fingerprint)

    def invalidar(self, username: str) -> None:
        for chave in [k for k in self._ativas if k[0] == username]:
            del self._ativas[chave]

    @staticmethod
    def _conferir(saida: ChavePublicaOut) -> ChavePublica:
        chave = carregar_publica(saida.public_key)
        if chave.key_id != saida.key_id or chave.fingerprint != saida.fingerprint or chave.modo != saida.modo:
            raise ChaveSuspeita(f"a chave entregue não corresponde ao key_id {saida.key_id}")
        return chave
