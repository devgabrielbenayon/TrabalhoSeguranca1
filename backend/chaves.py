"""Regras do diretório de chaves públicas, usadas pelo cadastro e (fase 5) pela troca."""

from __future__ import annotations

import base64

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Client, Conversation, KeyAccess, KeyEvent, PublicKey
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.chaves import ChavePublica, carregar_publica
from shared.crypto.prova import mensagem_prova
from shared.schemas import ChavePublicaOut


def validar_publica(modo: str, texto: str) -> ChavePublica:
    """Interpreta a chave enviada pelo cliente e confere modo e tamanho."""
    try:
        publica = carregar_publica(texto)
    except (ValueError, KeyError, TypeError) as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"chave pública ilegível: {erro}") from erro
    if publica.modo != modo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"a chave enviada é do modo {publica.modo}, não {modo}")
    bits = publica.numeros["n"].bit_length()
    if modo == "real" and bits < rsa_real.BITS_PADRAO:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"chave real com {bits} bits; o mínimo é {rsa_real.BITS_PADRAO}")
    if modo == "didatico" and not rsa_didatico.BITS_MIN <= bits <= rsa_didatico.BITS_MAX:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"chave didática com {bits} bits; use de {rsa_didatico.BITS_MIN} a {rsa_didatico.BITS_MAX}",
        )
    return publica


def conferir_prova(publica: ChavePublica, prova_b64: str, acao: str, username: str, nonce: str = "") -> None:
    """Prova de posse: a assinatura só confere se quem enviou tem a privada correspondente."""
    try:
        assinatura = base64.b64decode(prova_b64, validate=True)
    except ValueError:
        assinatura = b""
    if not publica.verificar(mensagem_prova(acao, username, publica.key_id, nonce), assinatura):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"prova de posse inválida para a chave {publica.key_id}")


def publicar(db: Session, cliente: Client, publica: ChavePublica) -> PublicKey:
    if db.scalar(select(PublicKey).where(PublicKey.key_id == publica.key_id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "esta chave pública já foi publicada")
    registro = PublicKey(
        key_id=publica.key_id,
        dono=cliente,
        modo=publica.modo,
        public_key=publica.exportar(),
        fingerprint=publica.fingerprint,
    )
    db.add(registro)
    db.add(KeyEvent(client_id=cliente.id, tipo="criada", key_id=publica.key_id, fingerprint=publica.fingerprint))
    return registro


def interessados(db: Session, dono: Client) -> set[int]:
    """Quem pode ter a chave de `dono` em cache: quem já a buscou e quem conversa com ele."""
    ids = set(db.scalars(select(KeyAccess.client_id).where(KeyAccess.owner_id == dono.id)))
    for conversa in db.scalars(select(Conversation).where(Conversation.membros.contains(dono))):
        ids.update(m.id for m in conversa.membros)
    ids.discard(dono.id)
    return ids


def chave_ativa(db: Session, client_id: int, modo: str) -> PublicKey | None:
    return db.scalar(
        select(PublicKey).where(PublicKey.client_id == client_id, PublicKey.modo == modo, PublicKey.status == "ativa")
    )


def para_saida(registro: PublicKey) -> ChavePublicaOut:
    return ChavePublicaOut(
        username=registro.dono.username,
        modo=registro.modo,
        key_id=registro.key_id,
        public_key=registro.public_key,
        fingerprint=registro.fingerprint,
        status=registro.status,
        criada_em=registro.criada_em,
    )
