"""Schemas Pydantic compartilhados entre back-end e front-end."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Um envelope por destinatário (seção 8.3 do plano). Blocos e assinatura em base64."""

    model_config = ConfigDict(populate_by_name=True)

    message_id: str
    conversation_id: int
    from_: str = Field(alias="from")
    from_key_id: str
    to: str
    to_key_id: str
    mode: Literal["didatico", "real"]
    sent_at: str
    blocks: list[str]
    signature: str = ""

    def dados_assinados(self) -> bytes:
        """JSON canônico de todos os campos exceto a assinatura."""
        campos = self.model_dump(by_alias=True, exclude={"signature"})
        return json.dumps(campos, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
