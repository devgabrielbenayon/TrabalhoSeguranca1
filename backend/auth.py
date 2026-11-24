"""Senhas (argon2), tokens de sessão opacos e limite de tentativas de login."""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Callable

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


_HASH_FICTICIO = _hasher.hash(secrets.token_urlsafe(16))


def gastar_tempo_de_verificacao(senha: str) -> None:
    """Para usuário inexistente: roda o argon2 do mesmo jeito, senão a resposta mais rápida revela quem tem conta."""
    verificar_senha(_HASH_FICTICIO, senha)


class LimiteTentativas:
    """Janela deslizante de falhas de login, por usuário e por IP, guardada em memória.

    O limite por IP é maior porque vários usuários podem sair do mesmo endereço (NAT, laboratório).
    """

    def __init__(
        self,
        por_usuario: int = 5,
        por_ip: int = 20,
        janela_s: float = 15 * 60,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limites = {"usuario": por_usuario, "ip": por_ip}
        self.janela_s = janela_s
        self._relogio = relogio
        self._falhas: dict[tuple[str, str], deque[float]] = {}

    def _recentes(self, chave: tuple[str, str]) -> deque[float]:
        falhas = self._falhas.get(chave, deque())
        corte = self._relogio() - self.janela_s
        while falhas and falhas[0] <= corte:
            falhas.popleft()
        if not falhas:
            self._falhas.pop(chave, None)
        return falhas

    def _chaves(self, username: str, ip: str) -> list[tuple[str, str]]:
        return [("usuario", username), ("ip", ip)]

    def espera(self, username: str, ip: str) -> int:
        """Segundos até poder tentar de novo; 0 = liberado."""
        espera = 0.0
        for chave in self._chaves(username, ip):
            falhas = self._recentes(chave)
            if len(falhas) >= self.limites[chave[0]]:
                espera = max(espera, falhas[0] + self.janela_s - self._relogio())
        return math.ceil(espera)

    def falhou(self, username: str, ip: str) -> None:
        agora_ = self._relogio()
        for chave in self._chaves(username, ip):
            self._falhas.setdefault(chave, deque()).append(agora_)

    def acertou(self, username: str) -> None:
        self._falhas.pop(("usuario", username), None)


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
