"""TraceEvent: registro de cada etapa criptográfica, fonte de todas as visualizações."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


@dataclass
class TraceEvent:
    etapa: str
    ator: str
    entrada: Any = None
    saida: Any = None
    duracao_ms: float = 0.0
    message_id: str | None = None
    detalhes: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Tracer:
    """Coleta TraceEvents de um ator (cliente ou servidor).

    `destino` recebe cada evento assim que ele termina (ex.: barramento do Inspetor).
    Com `ativo=False` nada é registrado e as funções de cripto pulam os detalhes caros.
    """

    def __init__(
        self,
        ator: str,
        destino: Callable[[TraceEvent], None] | None = None,
        ativo: bool = True,
    ) -> None:
        self.ator = ator
        self.ativo = ativo
        self.eventos: list[TraceEvent] = []
        self._destino = destino

    @contextmanager
    def etapa(
        self, nome: str, entrada: Any = None, message_id: str | None = None
    ) -> Iterator[TraceEvent]:
        evento = TraceEvent(etapa=nome, ator=self.ator, entrada=entrada, message_id=message_id)
        inicio = time.perf_counter()
        try:
            yield evento
        except Exception as erro:
            evento.detalhes["erro"] = f"{type(erro).__name__}: {erro}"
            raise
        finally:
            evento.duracao_ms = (time.perf_counter() - inicio) * 1000
            if self.ativo:
                self.eventos.append(evento)
                if self._destino is not None:
                    self._destino(evento)


SEM_RASTREIO = Tracer("nulo", ativo=False)
