"""Keystore local: as chaves privadas do usuário, por key_id. Nunca são enviadas ao servidor.

Estrutura em disco: <raiz>/<username>/
    index.json          chaves conhecidas e a ativa de cada modo
    <key_id>.pem        modo real, PKCS#8 cifrado com a senha do usuário
    <key_id>.json       modo didático, em claro (chave de brinquedo, insegura por construção)

Privadas antigas ficam guardadas depois de uma troca para ler o histórico (fluxo 5.4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.crypto.chaves import ChavePrivada, Modo
from shared.crypto.rsa_didatico import PrivadaDidatica
from shared.crypto.rsa_real import PrivadaReal


class ChaveNaoEncontrada(KeyError):
    pass


class Keystore:
    def __init__(self, raiz: Path | str, username: str, senha: str) -> None:
        self.pasta = Path(raiz) / username
        self._senha = senha
        self._carregadas: dict[str, ChavePrivada] = {}

    # ------------------------------------------------------------ índice

    @property
    def _arquivo_indice(self) -> Path:
        return self.pasta / "index.json"

    def _ler_indice(self) -> dict:
        if not self._arquivo_indice.exists():
            return {"ativas": {}, "chaves": {}}
        return json.loads(self._arquivo_indice.read_text(encoding="utf-8"))

    def _gravar_indice(self, indice: dict) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._arquivo_indice.write_text(json.dumps(indice, indent=2), encoding="utf-8")

    def existe(self) -> bool:
        return bool(self._ler_indice()["chaves"])

    # ------------------------------------------------------------ operações

    def guardar(self, privada: ChavePrivada, ativa: bool = True) -> None:
        key_id = privada.publica.key_id
        self.pasta.mkdir(parents=True, exist_ok=True)
        if isinstance(privada, PrivadaReal):
            arquivo = f"{key_id}.pem"
            (self.pasta / arquivo).write_bytes(privada.exportar(self._senha))
        else:
            arquivo = f"{key_id}.json"
            (self.pasta / arquivo).write_text(privada.exportar(), encoding="utf-8")

        indice = self._ler_indice()
        indice["chaves"][key_id] = {
            "modo": privada.modo,
            "arquivo": arquivo,
            "criada_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if ativa:
            indice["ativas"][privada.modo] = key_id
        self._gravar_indice(indice)
        self._carregadas[key_id] = privada

    def carregar(self, key_id: str) -> ChavePrivada:
        if key_id in self._carregadas:
            return self._carregadas[key_id]
        info = self._ler_indice()["chaves"].get(key_id)
        if info is None or not (self.pasta / info["arquivo"]).exists():
            raise ChaveNaoEncontrada(key_id)
        caminho = self.pasta / info["arquivo"]
        if info["modo"] == "real":
            privada: ChavePrivada = PrivadaReal.carregar(caminho.read_bytes(), self._senha)
        else:
            privada = PrivadaDidatica.carregar(caminho.read_text(encoding="utf-8"))
        self._carregadas[key_id] = privada
        return privada

    def ativa(self, modo: Modo) -> ChavePrivada | None:
        key_id = self._ler_indice()["ativas"].get(modo)
        return self.carregar(key_id) if key_id else None

    def listar(self) -> list[dict]:
        indice = self._ler_indice()
        ativas = set(indice["ativas"].values())
        return [{"key_id": k, **info, "ativa": k in ativas} for k, info in indice["chaves"].items()]

    def apagar(self, key_id: str) -> None:
        """Simulação "apagar privada": as mensagens cifradas para esta chave ficam ilegíveis."""
        indice = self._ler_indice()
        info = indice["chaves"].pop(key_id, None)
        if info is None:
            raise ChaveNaoEncontrada(key_id)
        (self.pasta / info["arquivo"]).unlink(missing_ok=True)
        indice["ativas"] = {m: k for m, k in indice["ativas"].items() if k != key_id}
        self._gravar_indice(indice)
        self._carregadas.pop(key_id, None)
