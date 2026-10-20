"""Senhas (argon2) e tokens de sessão opacos."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import agora, get_db
from backend.models import Client, Sessao

VALIDADE_TOKEN = timedelta(hours=12)

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


def hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha_hash: str, senha: str) -> bool:
    try:
        return _hasher.verify(senha_hash, senha)
    except VerificationError:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def emitir_token(db: Session, cliente: Client) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expira_em = agora() + VALIDADE_TOKEN
    db.add(Sessao(token_hash=_hash_token(token), client_id=cliente.id, expira_em=expira_em))
    db.commit()
    return token, expira_em


def revogar_token(db: Session, token: str) -> None:
    sessao = db.get(Sessao, _hash_token(token))
    if sessao is not None:
        db.delete(sessao)
        db.commit()


def cliente_do_token(db: Session, token: str) -> Client | None:
    """Também usado pelo WebSocket, que recebe o token na query string."""
    sessao = db.get(Sessao, _hash_token(token))
    if sessao is None or sessao.expira_em < agora():
        return None
    cliente = db.scalar(select(Client).where(Client.id == sessao.client_id))
    return cliente if cliente is not None and cliente.ativo else None


def token_da_requisicao(credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credenciais is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token ausente", headers={"WWW-Authenticate": "Bearer"})
    return credenciais.credentials


def usuario_atual(token: str = Depends(token_da_requisicao), db: Session = Depends(get_db)) -> Client:
    cliente = cliente_do_token(db, token)
    if cliente is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido ou expirado", headers={"WWW-Authenticate": "Bearer"})
    return cliente


def admin_atual(cliente: Client = Depends(usuario_atual)) -> Client:
    """CRUD de servidores, remoção de outros clientes e Observador: só administradores."""
    if not cliente.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "apenas administradores")
    return cliente
