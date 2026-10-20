"""CRUD de clientes (RF12). A criação é o cadastro do Passo 0 (POST /api/auth/register).

Remover é desativar: o usuário some das listas e não entra mais, as chaves dele são revogadas
(ninguém consegue cifrar para ele) e os contatos são avisados. As linhas ficam para que as mensagens
antigas continuem verificáveis por quem as recebeu.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend import chaves, nos
from backend.auth import usuario_atual, verificar_senha
from backend.db import agora, get_db
from backend.models import Client, KeyEvent, PublicKey, Server, Sessao
from shared.schemas import ClienteEdicaoIn, ClienteOut, RemocaoClienteIn

router = APIRouter(prefix="/api", tags=["clientes"])


def para_saida(cliente: Client, online: set[int]) -> ClienteOut:
    return ClienteOut(
        id=cliente.id,
        username=cliente.username,
        nome=cliente.nome,
        avatar=cliente.avatar,
        is_admin=cliente.is_admin,
        ativo=cliente.ativo,
        criado_em=cliente.criado_em,
        server_id=cliente.server_id,
        servidor=cliente.servidor.nome if cliente.servidor is not None else None,
        modos_ativos=sorted({c.modo for c in cliente.chaves if c.status == "ativa"}),
        online=cliente.id in online,
    )


@router.get("/clients", response_model=list[ClienteOut])
def listar(request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[ClienteOut]:
    """Administradores veem também os removidos."""
    consulta = select(Client).order_by(Client.username)
    if not eu.is_admin:
        consulta = consulta.where(Client.ativo)
    online = request.app.state.relay.conectados()
    return [para_saida(c, online) for c in db.scalars(consulta)]


@router.get("/clients/{client_id}", response_model=ClienteOut)
def detalhar(client_id: int, request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> ClienteOut:
    return para_saida(_buscar(db, client_id, eu), request.app.state.relay.conectados())


@router.put("/clients/{client_id}", response_model=ClienteOut)
async def editar(
    client_id: int, dados: ClienteEdicaoIn, request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)
) -> ClienteOut:
    alvo = _buscar(db, client_id, eu)
    if alvo.id != eu.id and not eu.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "só é possível editar o próprio perfil")
    # só os campos enviados; avatar null apaga o avatar, os outros null são ignorados
    campos = {c for c in dados.model_fields_set if getattr(dados, c) is not None or c == "avatar"}
    if campos & {"server_id", "is_admin", "ativo"} and not eu.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "apenas administradores mudam nó, papel ou reativam clientes")

    if "nome" in campos:
        alvo.nome = dados.nome.strip() or alvo.nome
    if "avatar" in campos:
        alvo.avatar = (dados.avatar or "").strip() or None
    if "server_id" in campos:
        no = db.get(Server, dados.server_id)
        if no is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "nó não encontrado")
        if not no.ativo:
            raise HTTPException(status.HTTP_409_CONFLICT, f"o nó {no.nome} está desligado")
        alvo.server_id = no.id
    if "is_admin" in campos and dados.is_admin != alvo.is_admin:
        if not dados.is_admin:
            _garantir_outro_admin(db, alvo)
        alvo.is_admin = dados.is_admin
    if "ativo" in campos:
        alvo.ativo = True  # volta sem chave ativa: publica uma nova pelo fluxo de troca ao entrar
    db.commit()

    if campos & {"server_id", "ativo"}:
        await nos.topologia_mudou(request.app.state, db)
    db.refresh(alvo)
    return para_saida(alvo, request.app.state.relay.conectados())


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover(
    client_id: int,
    request: Request,
    dados: RemocaoClienteIn | None = None,
    eu: Client = Depends(usuario_atual),
    db: Session = Depends(get_db),
) -> None:
    alvo = _buscar(db, client_id, eu)
    if alvo.id == eu.id:
        if dados is None or not dados.senha or not verificar_senha(eu.senha_hash, dados.senha):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "confirme a senha para remover a própria conta")
    elif not eu.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "apenas administradores removem outros clientes")
    if not alvo.ativo:
        raise HTTPException(status.HTTP_409_CONFLICT, "cliente já removido")
    if alvo.is_admin:
        _garantir_outro_admin(db, alvo)

    revogadas = db.scalars(select(PublicKey).where(PublicKey.client_id == alvo.id, PublicKey.status == "ativa")).all()
    for chave in revogadas:
        chave.status, chave.substituida_em = "revogada", agora()
        db.add(KeyEvent(client_id=alvo.id, tipo="revogada", key_id=chave.key_id, fingerprint=chave.fingerprint))
    alvo.ativo = False
    db.execute(delete(Sessao).where(Sessao.client_id == alvo.id))  # derruba todos os logins
    db.commit()

    estado = request.app.state
    for chave in revogadas:
        aviso = {"type": "key_revoked", "user": alvo.username, "modo": chave.modo, "key_id": chave.key_id}
        for client_id_interessado in chaves.interessados(db, alvo):
            await estado.relay.enviar(client_id_interessado, aviso)
    await estado.relay.desconectar(alvo.id)
    await estado.observador.publicar({"type": "cliente_removido", "usuario": alvo.username, "por": eu.username})
    await nos.topologia_mudou(estado, db)


def _buscar(db: Session, client_id: int, eu: Client) -> Client:
    cliente = db.get(Client, client_id)
    if cliente is None or (not cliente.ativo and not eu.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cliente não encontrado")
    return cliente


def _garantir_outro_admin(db: Session, alvo: Client) -> None:
    outros = db.scalar(select(func.count(Client.id)).where(Client.is_admin, Client.ativo, Client.id != alvo.id))
    if not outros:
        raise HTTPException(status.HTTP_409_CONFLICT, "é o último administrador: promova outro antes")
