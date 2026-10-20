"""CRUD de servidores/nós (RF13): dados do nó, ligações com os vizinhos e liga/desliga.

Qualquer mudança recalcula os caminhos: clientes de um nó desligado ou removido migram para outro,
e envelopes que esperavam um caminho são entregues assim que ele existir.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from backend import nos
from backend.auth import admin_atual, usuario_atual
from backend.db import get_db
from backend.models import Client, Server, ServerLink
from shared.schemas import ServidorIn, ServidorOut, StatusServidorIn, TopologiaOut

router = APIRouter(prefix="/api", tags=["servidores"])


@router.get("/servers", response_model=list[ServidorOut])
def listar(eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> list[ServidorOut]:
    return nos.topologia(db).nos


@router.get("/servers/topology", response_model=TopologiaOut)
def topologia(request: Request, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> TopologiaOut:
    return nos.topologia(db, request.app.state.relay.conectados())


@router.post("/servers", status_code=status.HTTP_201_CREATED, response_model=ServidorOut)
async def criar(dados: ServidorIn, request: Request, eu: Client = Depends(admin_atual), db: Session = Depends(get_db)) -> ServidorOut:
    no = Server(
        nome=nos.nome_unico(db, dados.nome),
        host=dados.host.strip(),
        porta=dados.porta,
        regiao=dados.regiao.strip(),
        capacidade=dados.capacidade,
        ativo=dados.ativo,
    )
    db.add(no)
    db.flush()
    nos.definir_vizinhos(db, no, dados.vizinhos)
    await nos.topologia_mudou(request.app.state, db)
    return _saida(db, no.id)


@router.post("/servers/example", status_code=status.HTTP_201_CREATED, response_model=list[ServidorOut])
async def topologia_exemplo(request: Request, eu: Client = Depends(admin_atual), db: Session = Depends(get_db)) -> list[ServidorOut]:
    """Anel Manaus–Brasília–São Paulo–Recife, para a demonstração. Só quando não há nenhum nó."""
    if db.scalar(select(Server.id).limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "já existem nós cadastrados")
    nos.criar_topologia_exemplo(db)
    await nos.topologia_mudou(request.app.state, db)
    return nos.topologia(db).nos


@router.get("/servers/{server_id}", response_model=ServidorOut)
def detalhar(server_id: int, eu: Client = Depends(usuario_atual), db: Session = Depends(get_db)) -> ServidorOut:
    _buscar(db, server_id)
    return _saida(db, server_id)


@router.put("/servers/{server_id}", response_model=ServidorOut)
async def editar(
    server_id: int, dados: ServidorIn, request: Request, eu: Client = Depends(admin_atual), db: Session = Depends(get_db)
) -> ServidorOut:
    no = _buscar(db, server_id)
    no.nome = nos.nome_unico(db, dados.nome, exceto=no.id)
    no.host, no.porta, no.regiao = dados.host.strip(), dados.porta, dados.regiao.strip()
    no.capacidade, no.ativo = dados.capacidade, dados.ativo
    nos.definir_vizinhos(db, no, dados.vizinhos)
    await nos.topologia_mudou(request.app.state, db)
    return _saida(db, no.id)


@router.patch("/servers/{server_id}/status", response_model=ServidorOut)
async def mudar_status(
    server_id: int, dados: StatusServidorIn, request: Request, eu: Client = Depends(admin_atual), db: Session = Depends(get_db)
) -> ServidorOut:
    """Desligar simula a queda do nó: os clientes dele migram e os caminhos desviam dele."""
    no = _buscar(db, server_id)
    no.ativo = dados.ativo
    await nos.topologia_mudou(request.app.state, db)
    await request.app.state.observador.publicar({"type": "no", "no": no.nome, "ativo": no.ativo, "por": eu.username})
    return _saida(db, no.id)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover(server_id: int, request: Request, eu: Client = Depends(admin_atual), db: Session = Depends(get_db)) -> None:
    no = _buscar(db, server_id)
    db.execute(delete(ServerLink).where(or_(ServerLink.a_id == no.id, ServerLink.b_id == no.id)))
    db.execute(update(Client).where(Client.server_id == no.id).values(server_id=None))
    db.delete(no)
    await nos.topologia_mudou(request.app.state, db)


def _buscar(db: Session, server_id: int) -> Server:
    no = db.get(Server, server_id)
    if no is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nó não encontrado")
    return no


def _saida(db: Session, server_id: int) -> ServidorOut:
    return next(n for n in nos.topologia(db).nos if n.id == server_id)
