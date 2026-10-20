"""Passo 0 — cadastro com publicação da chave pública — e login."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import chaves, nos
from backend.auth import emitir_token, hash_senha, revogar_token, token_da_requisicao, usuario_atual, verificar_senha
from backend.db import get_db
from backend.models import Client
from shared.schemas import LoginIn, RegistroIn, RegistroOut, TokenOut, UsuarioOut

router = APIRouter(prefix="/api", tags=["autenticação"])


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=RegistroOut)
def registrar(dados: RegistroIn, request: Request, tarefas: BackgroundTasks, db: Session = Depends(get_db)) -> RegistroOut:
    if db.scalar(select(Client).where(Client.username == dados.username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "nome de usuário já existe")

    # valida tudo antes de gravar qualquer coisa
    publicas = []
    for chave in dados.chaves:
        publica = chaves.validar_publica(chave.modo, chave.public_key)
        chaves.conferir_prova(publica, chave.prova, "registro", dados.username)
        publicas.append(publica)

    primeiro_usuario = db.scalar(select(func.count(Client.id))) == 0
    cliente = Client(
        username=dados.username,
        nome=dados.nome,
        senha_hash=hash_senha(dados.senha),
        is_admin=primeiro_usuario,  # o primeiro cadastro administra os CRUDs
    )
    db.add(cliente)
    db.flush()
    registros = [chaves.publicar(db, cliente, publica) for publica in publicas]
    nos.realocar(db)  # entra no nó ligado menos ocupado
    db.commit()

    estado = request.app.state
    tarefas.add_task(estado.observador.publicar, {"type": "topologia", **nos.topologia(db, estado.relay.conectados()).model_dump()})
    return RegistroOut(usuario=UsuarioOut.model_validate(cliente), chaves=[chaves.para_saida(r) for r in registros])


@router.post("/auth/login", response_model=TokenOut)
def login(dados: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    cliente = db.scalar(select(Client).where(Client.username == dados.username.strip().lower()))
    # mesma resposta para usuário inexistente e senha errada: não revela quem existe
    if cliente is None or not cliente.ativo or not verificar_senha(cliente.senha_hash, dados.senha):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário ou senha incorretos")
    token, expira_em = emitir_token(db, cliente)
    return TokenOut(token=token, expira_em=expira_em, usuario=UsuarioOut.model_validate(cliente))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: str = Depends(token_da_requisicao), db: Session = Depends(get_db)) -> None:
    revogar_token(db, token)


@router.get("/me", response_model=UsuarioOut)
def eu(cliente: Client = Depends(usuario_atual)) -> Client:
    return cliente
