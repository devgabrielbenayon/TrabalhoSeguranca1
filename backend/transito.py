"""Rastro de trânsito do servidor: cada passo de um envelope vira um TraceRegistro (GET /api/trace)
e um evento do Observador (/ws/observer).

Só entra o que o servidor enxerga: metadados, key_ids, tamanhos e o cifrado. Nunca texto claro.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from sqlalchemy.orm import Session

from backend.models import TraceRegistro

RELAY_CENTRAL = "relay"  # ator dos eventos quando não há nós cadastrados


def registrar(
    db: Session, message_id: str | None, etapa: str, ator: str, entrada: Any = None, saida: Any = None, duracao_ms: float = 0.0
) -> None:
    db.add(TraceRegistro(
        message_id=message_id,
        etapa=etapa,
        ator=ator,
        entrada=json.dumps(entrada, ensure_ascii=False),
        saida=json.dumps(saida, ensure_ascii=False),
        duracao_ms=duracao_ms,
    ))


def registrar_saltos(db: Session, envelope: dict, caminho: list[str]) -> None:
    """Um evento por nó: de onde o envelope veio e para onde é repassado (sempre cifrado)."""
    de, para = envelope["from"], envelope["to"]
    for i, no in enumerate(caminho):
        anterior = f"@{de}" if i == 0 else caminho[i - 1]
        seguinte = f"@{para}" if i == len(caminho) - 1 else caminho[i + 1]
        registrar(db, envelope["message_id"], "salto", no, {"de": anterior, "para": para}, {"repassa_para": seguinte})


def registrar_desfecho(db: Session, envelope: dict, ator: str, status: str) -> None:
    """entregue (repassado pelo WebSocket) ou fila (destinatário offline / sem caminho entre os nós)."""
    if status == "entregue":
        registrar(db, envelope["message_id"], "entregue", ator, {"para": envelope["to"]}, "repassado pelo WebSocket")
    else:
        registrar(db, envelope["message_id"], "fila", ator, {"para": envelope["to"]}, {"motivo": status})


def tamanho_cifrado(envelope: dict) -> int:
    return sum(len(base64.b64decode(b)) for b in envelope["blocks"])


def evento_transito(envelope: dict, caminho: list[str] | None, status: str, **extra: Any) -> dict:
    """Evento do Observador para um envelope: tudo o que o servidor sabe dele, inclusive o cifrado."""
    return {
        "type": "transito",
        "message_id": envelope["message_id"],
        "conversation_id": envelope["conversation_id"],
        "de": envelope["from"],
        "para": envelope["to"],
        "modo": envelope["mode"],
        "caminho": caminho,
        "status": status,  # entregue / offline / sem_rota
        "blocos": len(envelope["blocks"]),
        "bytes": tamanho_cifrado(envelope),
        "envelope": envelope,
        **extra,
    }
