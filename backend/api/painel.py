"""Rotas de apoio às telas de visualização: rastro de trânsito (Inspetor), contadores (Dashboard)
e a adulteração de demonstração (Observador)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.auth import admin_atual, usuario_atual
from backend.db import get_db
from backend.models import Client, Conversation, EnvelopeRegistro, Message, Server, TraceRegistro
from shared.schemas import AdulteracaoIn, EstatisticasOut, EventoTransitoOut

router = APIRouter(prefix="/api", tags=["painéis"])


@router.get("/trace/{message_id}", response_model=list[EventoTransitoOut])
def rastro(message_id: str, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[EventoTransitoOut]:
    """TraceEvents do servidor para uma mensagem: só para quem participa da conversa (ou administradores)."""
    mensagem = db.get(Message, message_id)
    conversa = db.get(Conversation, mensagem.conversation_id) if mensagem is not None else None
    if conversa is None or (eu not in conversa.membros and not eu.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mensagem não encontrada")
    registros = db.scalars(select(TraceRegistro).where(TraceRegistro.message_id == message_id).order_by(TraceRegistro.id))
    return [
        EventoTransitoOut(
            etapa=r.etapa, ator=r.ator, entrada=json.loads(r.entrada), saida=json.loads(r.saida), duracao_ms=r.duracao_ms, ts=r.ts
        )
        for r in registros
    ]


@router.get("/stats", response_model=EstatisticasOut)
def estatisticas(request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> EstatisticasOut:
    def contar(consulta) -> int:
        return db.scalar(consulta) or 0

    return EstatisticasOut(
        clientes=contar(select(func.count(Client.id)).where(Client.ativo)),
        online=len(request.app.state.relay.conectados()),
        servidores=contar(select(func.count(Server.id))),
        servidores_ativos=contar(select(func.count(Server.id)).where(Server.ativo)),
        conversas=contar(select(func.count(Conversation.id))),
        mensagens=contar(select(func.count(Message.id))),
        envelopes_pendentes=contar(select(func.count(EnvelopeRegistro.id)).where(EnvelopeRegistro.status == "pendente")),
        minhas_conversas=contar(select(func.count(Conversation.id)).where(Conversation.membros.contains(eu))),
        minhas_mensagens=contar(select(func.count(Message.id)).where(Message.sender_id == eu.id)),
    )


@router.get("/demo/tamper", response_model=AdulteracaoIn)
def adulteracao(request: Request, eu: Client = Depends(admin_atual)) -> AdulteracaoIn:
    return AdulteracaoIn(ativo=request.app.state.relay.adulterar_proximo)


@router.put("/demo/tamper", response_model=AdulteracaoIn)
async def armar_adulteracao(dados: AdulteracaoIn, request: Request, eu: Client = Depends(admin_atual)) -> AdulteracaoIn:
    """Servidor malicioso: altera um bloco do próximo envelope. O destinatário rejeita pela assinatura."""
    request.app.state.relay.adulterar_proximo = dados.ativo
    await request.app.state.observador.publicar({"type": "adulteracao", "ativo": dados.ativo, "por": eu.username})
    return dados
