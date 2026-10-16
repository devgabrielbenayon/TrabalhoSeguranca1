"""Conversas (1:1 e grupo) e histórico de envelopes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import usuario_atual
from backend.db import get_db
from backend.models import Client, Conversation, EnvelopeRegistro, Message
from shared.schemas import ConversaIn, ConversaOut, Envelope

router = APIRouter(prefix="/api", tags=["conversas"])


def para_saida(conversa: Conversation) -> ConversaOut:
    return ConversaOut(
        id=conversa.id,
        tipo=conversa.tipo,
        modo=conversa.modo,
        participantes=[m.username for m in conversa.membros],
        e2e_ativo=conversa.e2e_ativo,
        criada_em=conversa.criada_em,
    )


@router.post("/conversations", response_model=ConversaOut)
async def criar_conversa(
    dados: ConversaIn, request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)
) -> ConversaOut:
    nomes = {u.strip().lower() for u in dados.participantes} - {eu.username}
    if not nomes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "informe ao menos um outro participante")
    outros = db.scalars(select(Client).where(Client.username.in_(nomes), Client.ativo)).all()
    faltando = nomes - {c.username for c in outros}
    if faltando:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"usuários não encontrados: {', '.join(sorted(faltando))}")

    membros = sorted([eu, *outros], key=lambda c: c.username)
    tipo = "1:1" if len(membros) == 2 else "grupo"
    if tipo == "1:1":
        existente = _conversa_1a1(db, eu, outros[0], dados.modo)
        if existente is not None:
            return para_saida(existente)

    conversa = Conversation(tipo=tipo, modo=dados.modo, membros=membros)
    db.add(conversa)
    db.commit()
    saida = para_saida(conversa)
    # avisa os outros participantes conectados para a conversa aparecer na lista deles
    for membro in outros:
        await request.app.state.relay.enviar(membro.id, {"type": "conversation", "conversation": saida.model_dump(mode="json")})
    return saida


@router.get("/conversations", response_model=list[ConversaOut])
def minhas_conversas(eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[ConversaOut]:
    conversas = db.scalars(select(Conversation).where(Conversation.membros.contains(eu)).order_by(Conversation.id)).all()
    return [para_saida(c) for c in conversas]


@router.get("/messages", response_model=list[Envelope])
def historico(
    conversation_id: int = Query(), eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)
) -> list[Envelope]:
    """Só os envelopes endereçados a quem pede (inclusive as próprias cópias). Sempre cifrados."""
    conversa = db.get(Conversation, conversation_id)
    if conversa is None or eu not in conversa.membros:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversa não encontrada")
    registros = db.scalars(
        select(EnvelopeRegistro)
        .join(Message, Message.id == EnvelopeRegistro.message_id)
        .where(Message.conversation_id == conversation_id, EnvelopeRegistro.recipient_id == eu.id)
        .order_by(Message.recebida_em, EnvelopeRegistro.id)
    ).all()
    return [Envelope.model_validate_json(r.conteudo) for r in registros]


def _conversa_1a1(db: Session, a: Client, b: Client, modo: str) -> Conversation | None:
    candidatas = db.scalars(
        select(Conversation).where(Conversation.tipo == "1:1", Conversation.modo == modo, Conversation.membros.contains(a))
    ).all()
    return next((c for c in candidatas if b in c.membros), None)
