"""Nós e caminhos (RF13), rastro de trânsito do servidor e Observador (RF15) — direto na API."""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from starlette.websockets import WebSocketDisconnect

from backend import nos
from backend.db import criar_tabelas
from backend.main import criar_app
from backend.models import Client, EnvelopeRegistro
from shared.crypto import rsa_didatico
from shared.schemas import Envelope
from tests.test_api_relay import Usuario, _conversa, _pub


@pytest.fixture
def api():
    app = criar_app("sqlite://")
    with TestClient(app) as cliente:
        cliente.app_state = app.state
        yield cliente


@pytest.fixture
def alice(api):  # primeiro cadastro: administradora, no nó Manaus
    return Usuario(api, "alice", rsa_didatico.gerar(32))


@pytest.fixture
def bob(api):  # São Paulo: não é vizinho de Manaus
    return Usuario(api, "bob", rsa_didatico.gerar(32))


@pytest.fixture
def carol(api):  # Brasília
    return Usuario(api, "carol", rsa_didatico.gerar(32))


def _nos(api, usuario) -> dict[str, dict]:
    return {n["nome"]: n for n in api.get("/api/servers", headers=usuario.headers).json()}


def _status(api, usuario, nome, ativo):
    resposta = api.patch(f"/api/servers/{_nos(api, usuario)[nome]['id']}/status", json={"ativo": ativo}, headers=usuario.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _caminho(api, de: str, para: str):
    with api.app_state.sessionmaker() as db:
        origem = db.scalar(select(Client).where(Client.username == de))
        destino = db.scalar(select(Client).where(Client.username == para))
        return nos.caminho(db, origem.server_id, destino.server_id)


def _rastro(api, usuario, message_id):
    resposta = api.get(f"/api/trace/{message_id}", headers=usuario.headers)
    assert resposta.status_code == 200, resposta.text
    return [(e["etapa"], e["ator"]) for e in resposta.json()]


# ---------------------------------------------------------------- topologia


def test_banco_novo_vem_com_a_topologia_de_exemplo(api, alice, bob, carol):
    topologia = _nos(api, alice)
    assert list(topologia) == ["Manaus", "São Paulo", "Brasília", "Recife"]
    assert [topologia[n]["clientes"] for n in ("Manaus", "São Paulo", "Brasília")] == [["alice"], ["bob"], ["carol"]]
    ids = {nome: no["id"] for nome, no in topologia.items()}
    assert topologia["Manaus"]["vizinhos"] == sorted([ids["Brasília"], ids["Recife"]])


def test_sem_nos_o_relay_e_central_ate_criar_o_exemplo():
    app = criar_app("sqlite://", topologia_exemplo=False)
    with TestClient(app) as api:
        alice = Usuario(api, "alice", rsa_didatico.gerar(32))
        assert api.get("/api/servers", headers=alice.headers).json() == []
        api.app_state = app.state
        assert _caminho(api, "alice", "alice") == []  # caminho vazio = relay central

        resposta = api.post("/api/servers/example", headers=alice.headers)
        assert resposta.status_code == 201
        assert [n["nome"] for n in resposta.json()] == ["Manaus", "São Paulo", "Brasília", "Recife"]
        assert resposta.json()[0]["clientes"] == ["alice"]  # quem estava sem nó foi alocado
        assert api.post("/api/servers/example", headers=alice.headers).status_code == 409


def test_caminho_mais_curto_e_desvio_quando_um_no_cai(api, alice, bob):
    assert _caminho(api, "alice", "bob") == ["Manaus", "Brasília", "São Paulo"]
    _status(api, alice, "Brasília", False)
    assert _caminho(api, "alice", "bob") == ["Manaus", "Recife", "São Paulo"]
    _status(api, alice, "Recife", False)
    assert _caminho(api, "alice", "bob") is None
    assert _caminho(api, "alice", "alice") == ["Manaus"]


def test_crud_de_servidores_e_so_para_administradores(api, alice, bob):
    corpo = {"nome": "Belém", "regiao": "Norte", "porta": 9005, "vizinhos": []}
    assert api.post("/api/servers", json=corpo, headers=bob.headers).status_code == 403
    criado = api.post("/api/servers", json=corpo, headers=alice.headers)
    assert criado.status_code == 201, criado.text
    belem = criado.json()
    manaus = _nos(api, alice)["Manaus"]

    editado = api.put(f"/api/servers/{belem['id']}", json=corpo | {"vizinhos": [manaus["id"]], "capacidade": 5}, headers=alice.headers)
    assert editado.json()["vizinhos"] == [manaus["id"]] and editado.json()["capacidade"] == 5
    assert belem["id"] in _nos(api, alice)["Manaus"]["vizinhos"]  # a ligação vale nos dois sentidos

    assert api.post("/api/servers", json=corpo | {"nome": "belém"}, headers=alice.headers).status_code == 409
    assert api.post("/api/servers", json=corpo | {"nome": "X", "vizinhos": [999]}, headers=alice.headers).status_code == 404
    assert api.post("/api/servers", json=corpo | {"nome": "Y", "porta": 0}, headers=alice.headers).status_code == 422
    assert api.patch(f"/api/servers/{belem['id']}/status", json={"ativo": False}, headers=bob.headers).status_code == 403
    assert api.delete(f"/api/servers/{belem['id']}", headers=bob.headers).status_code == 403
    assert api.get(f"/api/servers/{belem['id']}", headers=bob.headers).json()["nome"] == "Belém"

    assert api.delete(f"/api/servers/{belem['id']}", headers=alice.headers).status_code == 204
    restantes = _nos(api, alice)
    assert "Belém" not in restantes and belem["id"] not in restantes["Manaus"]["vizinhos"]
    assert api.get(f"/api/servers/{belem['id']}", headers=alice.headers).status_code == 404


def test_desligar_ou_remover_um_no_migra_os_clientes(api, alice, bob):
    _status(api, alice, "São Paulo", False)
    topologia = _nos(api, alice)
    assert topologia["São Paulo"]["clientes"] == [] and topologia["Brasília"]["clientes"] == ["bob"]

    assert api.delete(f"/api/servers/{topologia['Brasília']['id']}", headers=alice.headers).status_code == 204
    assert _nos(api, alice)["Recife"]["clientes"] == ["bob"]  # o menos ocupado entre os ligados


# ---------------------------------------------------------------- envelopes pelos nós


def test_saltos_aparecem_no_rastro_do_servidor(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
        envio = alice.envio(conversa, "texto-secreto-123", _pub(bob))
        ws_a.send_json(envio)
        assert ws_b.receive_json()["type"] == "message"
        assert ws_a.receive_json() == {"type": "sent", "message_id": envio["message_id"], "offline": [], "sem_rota": []}
        ws_b.send_json({"type": "ack", "message_id": envio["message_id"]})
        assert ws_a.receive_json()["type"] == "delivered"

    assert _rastro(api, bob, envio["message_id"]) == [
        ("recebido", "Manaus"),
        ("salto", "Manaus"),
        ("salto", "Brasília"),
        ("salto", "São Paulo"),
        ("entregue", "São Paulo"),
        ("confirmado", "São Paulo"),
    ]
    eventos = api.get(f"/api/trace/{envio['message_id']}", headers=alice.headers).json()
    assert eventos[2]["entrada"] == {"de": "Manaus", "para": "bob"} and eventos[2]["saida"] == {"repassa_para": "São Paulo"}
    assert api.get(f"/api/trace/{envio['message_id']}", headers=carol.headers).status_code == 404  # não participa
    assert "texto-secreto-123" not in json.dumps(eventos)

    with api.app_state.sessionmaker() as db:
        registro = db.scalar(select(EnvelopeRegistro).where(EnvelopeRegistro.message_id == envio["message_id"], EnvelopeRegistro.recipient_id == 2))
        assert json.loads(registro.hops) == ["Manaus", "Brasília", "São Paulo"]


def test_sem_caminho_o_envelope_espera_e_sai_quando_o_no_volta(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    _status(api, alice, "Brasília", False)
    _status(api, alice, "Recife", False)
    with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
        envio = alice.envio(conversa, "espera o caminho", _pub(bob))
        ws_a.send_json(envio)
        assert ws_a.receive_json() == {"type": "sent", "message_id": envio["message_id"], "offline": [], "sem_rota": ["bob"]}

        _status(api, alice, "Recife", True)  # o caminho volta (por Recife) e a fila sai sozinha
        recebido = ws_b.receive_json()
        assert recebido["type"] == "message" and recebido["envelope"]["message_id"] == envio["message_id"]

    assert _rastro(api, alice, envio["message_id"]) == [
        ("recebido", "Manaus"),
        ("fila", "Manaus"),
        ("salto", "Manaus"),
        ("salto", "Recife"),
        ("salto", "São Paulo"),
        ("entregue", "São Paulo"),
    ]


def test_destinatario_offline_recebe_sem_repetir_os_saltos(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a:
        envio = alice.envio(conversa, "para depois", _pub(bob))
        ws_a.send_json(envio)
        assert ws_a.receive_json()["offline"] == ["bob"]
    with bob.ws(api) as ws_b:
        assert ws_b.receive_json()["envelope"]["message_id"] == envio["message_id"]
    assert _rastro(api, bob, envio["message_id"]) == [
        ("recebido", "Manaus"),
        ("salto", "Manaus"),
        ("salto", "Brasília"),
        ("salto", "São Paulo"),
        ("fila", "São Paulo"),
        ("entregue", "São Paulo"),
    ]


def test_adulteracao_de_demonstracao_quebra_a_assinatura(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    assert api.put("/api/demo/tamper", json={"ativo": True}, headers=bob.headers).status_code == 403
    assert api.put("/api/demo/tamper", json={"ativo": True}, headers=alice.headers).json() == {"ativo": True}
    publica_alice = alice.privadas["didatico"].publica

    with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
        for texto, deve_conferir in (("adulterada", False), ("intacta", True)):
            ws_a.send_json(alice.envio(conversa, texto, _pub(bob)))
            envelope = Envelope.model_validate(ws_b.receive_json()["envelope"])
            ws_a.receive_json()
            assinatura = base64.b64decode(envelope.signature)
            assert publica_alice.verificar(envelope.dados_assinados(), assinatura) is deve_conferir
    assert api.get("/api/demo/tamper", headers=alice.headers).json() == {"ativo": False}  # vale só para o próximo


# ---------------------------------------------------------------- Observador


@pytest.mark.parametrize("token", ["inventado", None])
def test_observador_so_para_administradores(api, alice, bob, token):
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(f"/ws/observer?token={token or bob.token}") as ws:
            ws.receive_json()


def test_observador_ve_o_transito_mas_nao_o_texto(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with api.websocket_connect(f"/ws/observer?token={alice.token}") as observador:
        topologia = observador.receive_json()
        assert topologia["type"] == "topologia" and len(topologia["nos"]) == 4
        assert observador.receive_json() == {"type": "historico", "eventos": []}
        with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
            envio = alice.envio(conversa, "segredo-observado", _pub(bob))
            ws_a.send_json(envio)
            ws_b.receive_json()
            ws_a.receive_json()
            eventos = [observador.receive_json() for _ in range(3)]
    assert [(e["type"], e.get("usuario")) for e in eventos[:2]] == [("conexao", "alice"), ("conexao", "bob")]
    transito = eventos[2]
    assert transito["type"] == "transito" and transito["status"] == "entregue"
    assert transito["caminho"] == ["Manaus", "Brasília", "São Paulo"]
    assert (transito["de"], transito["para"], transito["modo"]) == ("alice", "bob", "didatico")
    assert transito["envelope"] == next(e for e in envio["envelopes"] if e["to"] == "bob")  # exatamente o cifrado
    assert "segredo-observado" not in json.dumps(transito)
    assert eventos[0]["seq"] < eventos[1]["seq"] < eventos[2]["seq"]


# ---------------------------------------------------------------- Dashboard e banco


def test_estatisticas(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a:
        ws_a.send_json(alice.envio(conversa, "fica na fila", _pub(bob)))
        ws_a.receive_json()
        _status(api, alice, "Recife", False)
        numeros = api.get("/api/stats", headers=alice.headers).json()
    assert numeros == {
        "clientes": 2, "online": 1, "servidores": 4, "servidores_ativos": 3, "conversas": 1,
        "mensagens": 1, "envelopes_pendentes": 1, "minhas_conversas": 1, "minhas_mensagens": 1,
    }


def test_banco_de_versao_anterior_ganha_as_colunas_novas(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'antigo.db').as_posix()}")
    with engine.begin() as conexao:
        conexao.execute(text(
            "CREATE TABLE envelopes (id INTEGER PRIMARY KEY, message_id VARCHAR(32), recipient_id INTEGER, "
            "to_key_id VARCHAR(20), conteudo TEXT, status VARCHAR(10), entregue_em DATETIME)"
        ))
        conexao.execute(text("INSERT INTO envelopes VALUES (1, 'm', 1, 'k', '{}', 'pendente', NULL)"))
    criar_tabelas(engine)
    with engine.connect() as conexao:
        assert conexao.execute(text("SELECT hops FROM envelopes")).scalar() == "[]"
        assert conexao.execute(text("SELECT count(*) FROM trace_events")).scalar() == 0
