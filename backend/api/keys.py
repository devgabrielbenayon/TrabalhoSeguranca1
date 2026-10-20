"""Diretório de chaves públicas (passo 1 dos diagramas A → B e A → B e C)."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import chaves
from backend.auth import usuario_atual, verificar_senha
from backend.db import agora, get_db
from backend.models import Client, KeyAccess, KeyChallenge, KeyEvent, PublicKey
from shared.schemas import ChavePublicaOut, DesafioOut, DiretorioOut, ExclusaoChaveIn, Modo, TrocaChaveIn

router = APIRouter(prefix="/api", tags=["chaves"])

MAX_USUARIOS_POR_BUSCA = 50
VALIDADE_DESAFIO = timedelta(seconds=60)


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


@router.get("/keys/id/{key_id}", response_model=ChavePublicaOut)
def chave_por_id(key_id: str, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> ChavePublicaOut:
    """Qualquer chave já publicada, inclusive substituída: verificar a assinatura de mensagens antigas."""
    registro = db.scalar(select(PublicKey).where(PublicKey.key_id == key_id))
    if registro is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chave não encontrada")
    if registro.client_id != eu.id:
        _registrar_acesso(db, eu.id, registro)
        db.commit()
    return chaves.para_saida(registro)


@router.get("/me/keys", response_model=list[ChavePublicaOut])
def minhas_chaves(eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[ChavePublicaOut]:
    registros = db.scalars(select(PublicKey).where(PublicKey.client_id == eu.id).order_by(PublicKey.criada_em)).all()
    return [chaves.para_saida(r) for r in registros]


# ---------------------------------------------------------------- troca (fluxo 5.4)


@router.post("/keys/challenge", response_model=DesafioOut)
def desafio(eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> DesafioOut:
    registro = KeyChallenge(nonce=secrets.token_hex(16), client_id=eu.id, expira_em=agora() + VALIDADE_DESAFIO)
    db.add(registro)
    db.commit()
    return DesafioOut(nonce=registro.nonce, expira_em=registro.expira_em)


@router.put("/me/key", response_model=ChavePublicaOut)
async def trocar_chave(
    dados: TrocaChaveIn, request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)
) -> ChavePublicaOut:
    """Publica uma nova chave no modo. A antiga (se houver) vira `substituida` e os contatos são avisados.

    Também serve para voltar a ter chave depois de uma exclusão.
    """
    desafio = db.get(KeyChallenge, dados.nonce)
    if desafio is None or desafio.client_id != eu.id or desafio.usado or desafio.expira_em < agora():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "desafio inválido, expirado ou já usado")
    desafio.usado = True
    db.commit()  # queima o nonce mesmo que o resto falhe: não há segunda tentativa com ele

    nova = chaves.validar_publica(dados.modo, dados.public_key)
    chaves.conferir_prova(nova, dados.prova, "troca", eu.username, dados.nonce)

    antiga = chaves.chave_ativa(db, eu.id, dados.modo)
    if antiga is not None:
        antiga.status, antiga.substituida_em = "substituida", agora()
        db.add(KeyEvent(client_id=eu.id, tipo="substituida", key_id=antiga.key_id, fingerprint=antiga.fingerprint))
        db.flush()
    registro = chaves.publicar(db, eu, nova)
    db.commit()

    saida = chaves.para_saida(registro)
    aviso = {"type": "key_changed", "user": eu.username, "modo": dados.modo, "key_id": saida.key_id, "fingerprint": saida.fingerprint}
    avisados = chaves.interessados(db, eu)
    for client_id in avisados:
        await request.app.state.relay.enviar(client_id, aviso)
    await request.app.state.observador.publicar({
        "type": "chave", "evento": "trocada", "usuario": eu.username, "modo": dados.modo,
        "key_id": saida.key_id, "antiga": antiga.key_id if antiga else None, "avisados": len(avisados),
    })
    return saida


# ---------------------------------------------------------------- exclusão (fluxo 5.5)


@router.post("/me/key/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def excluir_chave(
    dados: ExclusaoChaveIn, request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)
) -> None:
    """Revoga a chave ativa do modo: ninguém mais consegue cifrar para este usuário até ele publicar outra."""
    if not verificar_senha(eu.senha_hash, dados.senha):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "senha incorreta")
    ativa = chaves.chave_ativa(db, eu.id, dados.modo)
    if ativa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"nenhuma chave ativa no modo {dados.modo}")
    ativa.status, ativa.substituida_em = "revogada", agora()
    db.add(KeyEvent(client_id=eu.id, tipo="revogada", key_id=ativa.key_id, fingerprint=ativa.fingerprint))
    db.commit()

    aviso = {"type": "key_revoked", "user": eu.username, "modo": dados.modo, "key_id": ativa.key_id}
    avisados = chaves.interessados(db, eu)
    for client_id in avisados:
        await request.app.state.relay.enviar(client_id, aviso)
    await request.app.state.observador.publicar({
        "type": "chave", "evento": "revogada", "usuario": eu.username, "modo": dados.modo,
        "key_id": ativa.key_id, "avisados": len(avisados),
    })


def _registrar_acesso(db: Session, client_id: int, registro: PublicKey) -> None:
    acesso = db.scalar(select(KeyAccess).where(KeyAccess.client_id == client_id, KeyAccess.owner_id == registro.client_id))
    if acesso is None:
        db.add(KeyAccess(client_id=client_id, owner_id=registro.client_id, key_id=registro.key_id))
        db.flush()
    elif registro.status == "ativa":
        acesso.key_id, acesso.ts = registro.key_id, agora()
