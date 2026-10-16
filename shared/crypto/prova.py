"""Prova de posse: o cliente assina esta mensagem com a privada para provar que a tem.

Usada no cadastro (Passo 0) e, com o nonce do servidor, na troca de chave.
O mesmo formato é montado no cliente (para assinar) e no servidor (para verificar).
"""

from __future__ import annotations

import json


def mensagem_prova(acao: str, username: str, key_id: str, nonce: str = "") -> bytes:
    campos = {"acao": acao, "key_id": key_id, "nonce": nonce, "username": username}
    return json.dumps(campos, sort_keys=True, separators=(",", ":")).encode("utf-8")
