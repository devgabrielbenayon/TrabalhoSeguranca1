"""Texto ↔ bytes ↔ blocos. Consequência do RSA puro: só se cifra um bloco menor que n por vez.

O conteúdo cifrado leva um cabeçalho interno (`from`, `message_id`) que o destinatário confere
contra o envelope externo — impede que outro usuário reassine o envelope de A como se fosse dele.
"""

from __future__ import annotations

import json

MAX_TEXTO_BYTES = 2000
PREENCHIMENTO = b"\x00"  # JSON em UTF-8 nunca contém byte nulo, então pode ser removido com segurança


class MensagemGrandeDemais(ValueError):
    pass


def codificar_conteudo(remetente: str, message_id: str, texto: str) -> bytes:
    tamanho = len(texto.encode("utf-8"))
    if tamanho > MAX_TEXTO_BYTES:
        raise MensagemGrandeDemais(f"mensagem com {tamanho} bytes; o limite é {MAX_TEXTO_BYTES}")
    conteudo = {"from": remetente, "message_id": message_id, "text": texto}
    return json.dumps(conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decodificar_conteudo(dados: bytes) -> dict:
    conteudo = json.loads(dados.decode("utf-8"))
    if not isinstance(conteudo, dict) or not {"from", "message_id", "text"} <= conteudo.keys():
        raise ValueError("conteúdo sem o cabeçalho interno")
    return conteudo


def dividir(dados: bytes, tamanho: int, completar: bool = False) -> list[bytes]:
    """Fatia em blocos de `tamanho` bytes; com `completar`, o último é preenchido com zeros."""
    if tamanho < 1:
        raise ValueError("tamanho de bloco inválido")
    if completar and len(dados) % tamanho:
        dados += PREENCHIMENTO * (tamanho - len(dados) % tamanho)
    return [dados[i : i + tamanho] for i in range(0, len(dados), tamanho)]


def juntar(blocos: list[bytes], remover_preenchimento: bool = False) -> bytes:
    dados = b"".join(blocos)
    return dados.rstrip(PREENCHIMENTO) if remover_preenchimento else dados
