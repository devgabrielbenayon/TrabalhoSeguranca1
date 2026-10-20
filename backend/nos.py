"""Nós de retransmissão (RF13): em qual nó fica cada cliente e por quais nós passa cada envelope.

Os nós são lógicos, todos dentro deste back-end: servem para mostrar os saltos no Observador.

- Um cliente fica sempre num nó ligado: se o dele é desligado ou removido, vai para o menos ocupado.
- O caminho é o de menos saltos entre o nó do remetente e o do destinatário, passando só por nós ligados.
- Sem nenhum nó cadastrado o relay é central (caminho vazio). Com nós, mas sem caminho, o envelope espera.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from backend.models import Client, Server, ServerLink
from shared.schemas import ClienteTopologia, ServidorOut, TopologiaOut

if TYPE_CHECKING:
    from starlette.datastructures import State

# Anel Manaus–Brasília–São Paulo–Recife–Manaus. Os ids seguem a ordem da tupla, então os dois primeiros
# clientes caem em Manaus e São Paulo, que não são vizinhos: a primeira conversa já passa por um nó
# intermediário, e desligar Brasília obriga o caminho a dar a volta por Recife.
TOPOLOGIA_EXEMPLO = (
    ("Manaus", "Norte", 9001),
    ("São Paulo", "Sudeste", 9002),
    ("Brasília", "Centro-Oeste", 9003),
    ("Recife", "Nordeste", 9004),
)
LIGACOES_EXEMPLO = (("Manaus", "Brasília"), ("Brasília", "São Paulo"), ("São Paulo", "Recife"), ("Recife", "Manaus"))


# ---------------------------------------------------------------- grafo


def vizinhos(db: Session) -> dict[int, set[int]]:
    grafo: dict[int, set[int]] = {}
    for ligacao in db.scalars(select(ServerLink)):
        grafo.setdefault(ligacao.a_id, set()).add(ligacao.b_id)
        grafo.setdefault(ligacao.b_id, set()).add(ligacao.a_id)
    return grafo


def definir_vizinhos(db: Session, no: Server, ids: Iterable[int]) -> None:
    ids = set(ids) - {no.id}
    existentes = set(db.scalars(select(Server.id).where(Server.id.in_(ids))))
    if ids - existentes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"nós inexistentes: {sorted(ids - existentes)}")
    db.execute(delete(ServerLink).where(or_(ServerLink.a_id == no.id, ServerLink.b_id == no.id)))
    for outro in sorted(ids):
        db.add(ServerLink(a_id=min(no.id, outro), b_id=max(no.id, outro)))


def caminho(db: Session, origem_id: int | None, destino_id: int | None) -> list[str] | None:
    """Nomes dos nós do caminho mais curto (busca em largura). [] = relay central; None = sem caminho agora."""
    nos = {s.id: s for s in db.scalars(select(Server))}
    if not nos:
        return []
    origem, destino = nos.get(origem_id), nos.get(destino_id)
    if origem is None or destino is None or not origem.ativo or not destino.ativo:
        return None
    grafo = vizinhos(db)
    anterior: dict[int, int | None] = {origem.id: None}
    fila = deque([origem.id])
    while fila:
        atual = fila.popleft()
        if atual == destino.id:
            ids: list[int] = []
            passo: int | None = atual
            while passo is not None:
                ids.append(passo)
                passo = anterior[passo]
            return [nos[i].nome for i in reversed(ids)]
        for proximo in sorted(grafo.get(atual, ())):
            if proximo not in anterior and nos[proximo].ativo:
                anterior[proximo] = atual
                fila.append(proximo)
    return None


# ---------------------------------------------------------------- clientes nos nós


def realocar(db: Session) -> list[Client]:
    """Põe num nó ligado todo cliente ativo que está sem nó ou num nó desligado. Devolve quem mudou."""
    ligados = db.scalars(select(Server).where(Server.ativo).order_by(Server.id)).all()
    if not ligados:
        return []
    carga = {s.id: 0 for s in ligados}
    clientes = db.scalars(select(Client).where(Client.ativo).order_by(Client.id)).all()
    for cliente in clientes:
        if cliente.server_id in carga:
            carga[cliente.server_id] += 1
    movidos = []
    for cliente in clientes:
        if cliente.server_id not in carga:
            destino = min(ligados, key=lambda s: (carga[s.id] / max(s.capacidade, 1), s.id))
            cliente.server_id = destino.id
            carga[destino.id] += 1
            movidos.append(cliente)
    return movidos


def nome_unico(db: Session, nome: str, exceto: int | None = None) -> str:
    nome = nome.strip()
    consulta = select(Server.id).where(func.lower(Server.nome) == nome.lower())
    if exceto is not None:
        consulta = consulta.where(Server.id != exceto)
    if not nome or db.scalar(consulta) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"já existe um nó chamado {nome!r}")
    return nome


def criar_topologia_exemplo(db: Session) -> list[Server]:
    nos = {nome: Server(nome=nome, regiao=regiao, porta=porta) for nome, regiao, porta in TOPOLOGIA_EXEMPLO}
    db.add_all(nos.values())
    db.flush()
    for a, b in LIGACOES_EXEMPLO:
        db.add(ServerLink(a_id=min(nos[a].id, nos[b].id), b_id=max(nos[a].id, nos[b].id)))
    realocar(db)
    db.flush()
    return list(nos.values())


# ---------------------------------------------------------------- saída


def para_saida(no: Server, grafo: dict[int, set[int]], clientes: list[str]) -> ServidorOut:
    return ServidorOut(
        id=no.id,
        nome=no.nome,
        host=no.host,
        porta=no.porta,
        regiao=no.regiao,
        capacidade=no.capacidade,
        ativo=no.ativo,
        vizinhos=sorted(grafo.get(no.id, ())),
        clientes=clientes,
    )


def topologia(db: Session, online: set[int] = frozenset()) -> TopologiaOut:
    grafo = vizinhos(db)
    clientes = db.scalars(select(Client).where(Client.ativo).order_by(Client.username)).all()
    por_no: dict[int | None, list[str]] = {}
    for cliente in clientes:
        por_no.setdefault(cliente.server_id, []).append(cliente.username)
    return TopologiaOut(
        nos=[para_saida(no, grafo, por_no.get(no.id, [])) for no in db.scalars(select(Server).order_by(Server.id))],
        clientes=[ClienteTopologia(username=c.username, server_id=c.server_id, online=c.id in online) for c in clientes],
    )


async def topologia_mudou(estado: State, db: Session) -> None:
    """Depois de qualquer mudança em nós, ligações ou clientes: realoca, avisa o Observador e
    entrega o que estava esperando por um caminho."""
    realocar(db)
    db.commit()
    await estado.observador.publicar({"type": "topologia", **topologia(db, estado.relay.conectados()).model_dump()})
    await estado.relay.reentregar(estado.sessionmaker, estado.observador)
