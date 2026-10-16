"""Diretório de chaves públicas (passo 1 dos diagramas A → B e A → B e C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import chaves
from backend.auth import usuario_atual
from backend.db import agora, get_db
from backend.models import Client, KeyAccess, PublicKey
from shared.schemas import ChavePublicaOut, DiretorioOut, Modo

router = APIRouter(prefix="/api", tags=["chaves"])

MAX_USUARIOS_POR_BUSCA = 50


@router.get("/keys", response_model=DiretorioOut)
def buscar_chaves(
    users: str = Query(description="usernames separados por vírgula", examples=["bob,carol"]),
    modo: Modo = "real",
    eu: Client = Depends(usuario_atual),
    db: Session = Depends(get_db),
) -> DiretorioOut:
    pedidos = list(dict.fromkeys(u.strip().lower() for u in users.split(",") if u.strip()))
    if not pedidos or len(pedidos) > MAX_USUARIOS_POR_BUSCA:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"informe de 1 a {MAX_USUARIOS_POR_BUSCA} usuários")

    ativas = db.scalars(
        select(PublicKey)
        .join(PublicKey.dono)
        .where(Client.username.in_(pedidos), Client.ativo, PublicKey.modo == modo, PublicKey.status == "ativa")
    ).all()
    encontradas = {registro.dono.username: registro for registro in ativas}

    for registro in ativas:
        if registro.client_id != eu.id:
            _registrar_acesso(db, eu.id, registro)
    db.commit()

    return DiretorioOut(
        chaves={u: chaves.para_saida(r) for u, r in encontradas.items()},
        sem_chave=[u for u in pedidos if u not in encontradas],
    )


@router.get("/me/keys", response_model=list[ChavePublicaOut])
def minhas_chaves(eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[ChavePublicaOut]:
    registros = db.scalars(select(PublicKey).where(PublicKey.client_id == eu.id).order_by(PublicKey.criada_em)).all()
    return [chaves.para_saida(r) for r in registros]


def _registrar_acesso(db: Session, client_id: int, registro: PublicKey) -> None:
    acesso = db.scalar(select(KeyAccess).where(KeyAccess.client_id == client_id, KeyAccess.owner_id == registro.client_id))
    if acesso is None:
        db.add(KeyAccess(client_id=client_id, owner_id=registro.client_id, key_id=registro.key_id))
    else:
        acesso.key_id, acesso.ts = registro.key_id, agora()
