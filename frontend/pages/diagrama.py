"""Diagrama da topologia em ECharts: nós num círculo, clientes ao redor do seu nó e o envelope
animado percorrendo o caminho (verde = cifrado; âmbar = parado na fila)."""

from __future__ import annotations

import math

from shared.schemas import TopologiaOut

ENVELOPE = "path://M0,0 L24,0 L24,16 L0,16 Z M0,0 L12,9 L24,0"
COR_CIFRADO = "#15803d"
COR_FILA = "#b45309"
COR_ADULTERADO = "#b91c1c"
RAIO_NOS, RAIO_CLIENTES = 1.0, 1.8
CENTRAL = "relay"  # sem nós cadastrados, o relay é um ponto só no centro


def ordem_no_circulo(topologia: TopologiaOut) -> list:
    """Nós na ordem de um percurso em profundidade pelas ligações: num anel, vizinhos ficam lado a lado
    no círculo e as ligações não se cruzam no meio."""
    por_id = {no.id: no for no in topologia.nos}
    visitados: list[int] = []

    def visitar(no_id: int) -> None:
        visitados.append(no_id)
        for vizinho in sorted(por_id[no_id].vizinhos):
            if vizinho in por_id and vizinho not in visitados:
                visitar(vizinho)

    for no in topologia.nos:
        if no.id not in visitados:
            visitar(no.id)
    return [por_id[i] for i in visitados]


def posicoes(topologia: TopologiaOut) -> dict[str, tuple[float, float]]:
    """Nós (pelo nome) num círculo a partir do topo, clientes (@nome) abertos em leque atrás do seu nó."""
    pos: dict[str, tuple[float, float]] = {}
    angulos: dict[int | None, float] = {}
    if not topologia.nos:
        pos[CENTRAL] = (0.0, 0.0)
        angulos[None] = math.pi / 2
    for i, no in enumerate(ordem_no_circulo(topologia)):
        angulo = math.pi / 2 - 2 * math.pi * i / len(topologia.nos)
        angulos[no.id] = angulo
        pos[no.nome] = (RAIO_NOS * math.cos(angulo), RAIO_NOS * math.sin(angulo))

    por_no: dict[int | None, list[str]] = {}
    for cliente in topologia.clientes:
        chave = cliente.server_id if cliente.server_id in angulos else None
        por_no.setdefault(chave, []).append(cliente.username)
    for chave, nomes in por_no.items():
        if chave is None and topologia.nos:  # sem nó, mas há nós: ficam embaixo, à parte
            for i, nome in enumerate(nomes):
                pos[f"@{nome}"] = (-1.5 + i * 0.6, -1.95)
            continue
        if chave is None:
            leque = [math.pi / 2 - 2 * math.pi * i / len(nomes) for i in range(len(nomes))]
        else:
            abertura = min(0.9, 0.32 * (len(nomes) - 1))
            leque = [angulos[chave] - abertura / 2 + (abertura * i / max(len(nomes) - 1, 1)) for i in range(len(nomes))]
        for nome, angulo in zip(nomes, leque):
            raio = 1.1 if chave is None else RAIO_CLIENTES
            pos[f"@{nome}"] = (raio * math.cos(angulo), raio * math.sin(angulo))
    return pos


def _lado_de_fora(x: float, y: float) -> str:
    """Rótulo do cliente do lado oposto ao centro, para não cruzar com a ligação até o nó."""
    if abs(y) >= abs(x):
        return "top" if y > 0 else "bottom"
    return "right" if x > 0 else "left"


def opcoes(
    topologia: TopologiaOut,
    caminho: list[str] | None = None,
    de: str | None = None,
    para: str | None = None,
    status: str = "entregue",
    adulterado: bool = False,
) -> dict:
    """Opções do ECharts. Sempre as mesmas 5 séries, para o NiceGUI atualizar sem recriar o gráfico."""
    pos = posicoes(topologia)
    no_por_id = {no.id: no for no in topologia.nos}
    no_do_cliente = {c.username: no_por_id[c.server_id].nome for c in topologia.clientes if c.server_id in no_por_id}
    no_do_cliente |= {c.username: CENTRAL for c in topologia.clientes if not topologia.nos}

    ligacoes = []
    for no in topologia.nos:
        for vizinho in no.vizinhos:
            if vizinho > no.id and vizinho in no_por_id:
                ligado = no.ativo and no_por_id[vizinho].ativo
                ligacoes.append({
                    "coords": [pos[no.nome], pos[no_por_id[vizinho].nome]],
                    "lineStyle": {"color": "#94a3b8" if ligado else "#e2e8f0", "type": "solid" if ligado else "dashed"},
                })
    acessos = [
        {"coords": [pos[f"@{c}"], pos[no]]} for c, no in no_do_cliente.items() if f"@{c}" in pos and no in pos
    ]

    em_destaque = set(caminho or [])
    nos = []
    for no in topologia.nos:
        nos.append({
            "name": no.nome,
            "value": list(pos[no.nome]),
            "symbol": "roundRect",
            "symbolSize": [104, 34],
            "itemStyle": {
                "color": ("#0f766e" if no.ativo else "#cbd5e1"),
                "borderColor": COR_CIFRADO if no.nome in em_destaque else "#ffffff",
                "borderWidth": 4 if no.nome in em_destaque else 1,
            },
            "label": {"show": True, "position": "inside", "formatter": no.nome + ("" if no.ativo else " ✕"),
                      "color": "#ffffff" if no.ativo else "#475569", "fontWeight": "bold"},
            "tooltip": {"formatter": f"{no.nome} · {no.regiao or 'sem região'}<br/>{no.host}:{no.porta}<br/>"
                                     f"{'ligado' if no.ativo else 'DESLIGADO'} · {len(no.clientes)}/{no.capacidade} clientes"},
        })
    if not topologia.nos:
        nos.append({"name": CENTRAL, "value": [0, 0], "symbol": "roundRect", "symbolSize": [104, 34],
                    "itemStyle": {"color": "#0f766e"}, "label": {"show": True, "position": "inside", "formatter": "relay central",
                                                              "color": "#ffffff", "fontWeight": "bold"}})

    clientes = []
    for cliente in topologia.clientes:
        nome = f"@{cliente.username}"
        envolvido = cliente.username in (de, para)
        clientes.append({
            "name": nome,
            "value": list(pos[nome]),
            "symbol": "circle",
            "symbolSize": 34 if envolvido else 26,
            "itemStyle": {"color": "#0369a1" if cliente.online else "#94a3b8",
                          "borderColor": COR_CIFRADO if envolvido else "#ffffff", "borderWidth": 3 if envolvido else 1},
            "label": {"show": True, "position": _lado_de_fora(*pos[nome]), "formatter": nome, "color": "#0f172a"},
            "tooltip": {"formatter": f"{nome} · {'online' if cliente.online else 'offline'}"
                                     f"<br/>nó: {no_do_cliente.get(cliente.username, 'nenhum')}"},
        })

    percurso, cor = [], COR_CIFRADO
    if de and para and f"@{de}" in pos and f"@{para}" in pos:
        if caminho is None:  # sem rota: parado no nó do remetente
            parada = no_do_cliente.get(de)
            pontos = [pos[f"@{de}"]] + ([pos[parada]] if parada in pos else [])
            cor = COR_FILA
        else:
            intermediarios = caminho or ([CENTRAL] if CENTRAL in pos else [])
            pontos = [pos[f"@{de}"], *[pos[n] for n in intermediarios if n in pos], pos[f"@{para}"]]
            cor = COR_ADULTERADO if adulterado else (COR_FILA if status == "offline" else COR_CIFRADO)
        if len(pontos) >= 2:
            percurso.append({"coords": pontos})

    return {
        "animation": True,
        "grid": {"left": 0, "right": 0, "top": 0, "bottom": 0},
        "xAxis": {"type": "value", "show": False, "min": -2.5, "max": 2.5},
        "yAxis": {"type": "value", "show": False, "min": -2.25, "max": 2.15},
        "tooltip": {"trigger": "item"},
        "series": [
            {"type": "lines", "coordinateSystem": "cartesian2d", "data": ligacoes, "silent": True, "z": 1,
             "lineStyle": {"width": 4, "opacity": 1}},
            {"type": "lines", "coordinateSystem": "cartesian2d", "data": acessos, "silent": True, "z": 1,
             "lineStyle": {"width": 1.5, "type": "dotted", "color": "#94a3b8", "opacity": 1}},
            {"type": "scatter", "data": nos, "z": 3},
            {"type": "scatter", "data": clientes, "z": 3},
            {"type": "lines", "coordinateSystem": "cartesian2d", "polyline": True, "data": percurso, "silent": True, "z": 2,
             "lineStyle": {"width": 6, "opacity": 0.45, "color": cor},
             "effect": {"show": True, "period": 3, "trailLength": 0, "symbol": ENVELOPE, "symbolSize": [24, 16],
                        "loop": True, "color": cor}},
        ],
    }
