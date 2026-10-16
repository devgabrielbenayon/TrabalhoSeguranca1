"""Conversas, histórico e regras do relay WebSocket — direto na API, com chaves didáticas (rápidas)."""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from backend.main import criar_app
from backend.models import EnvelopeRegistro
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.envelope import montar_envelopes
from shared.crypto.prova import mensagem_prova


class Usuario:
    def __init__(self, api, nome, *privadas):
        self.nome = nome
        self.privadas = {p.modo: p for p in privadas}
        chaves = []
        for p in privadas:
            prova = p.assinar(mensagem_prova("registro", nome, p.publica.key_id))
            chaves.append({"modo": p.modo, "public_key": p.publica.exportar(), "prova": base64.b64encode(prova).decode()})
        resposta = api.post("/api/auth/register", json={"username": nome, "nome": nome, "senha": "segredo123", "chaves": chaves})
        assert resposta.status_code == 201, resposta.text
        token = api.post("/api/auth/login", json={"username": nome, "senha": "segredo123"}).json()["token"]
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def ws(self, api):
        return api.websocket_connect(f"/ws?token={self.token}")

    def envio(self, conversa, texto, destinos, modo="didatico", **kwargs):
        envelopes = montar_envelopes(texto, self.nome, self.privadas[modo], destinos, conversa, **kwargs)
        return {
            "type": "send",
            "message_id": envelopes[0].message_id,
            "conversation_id": conversa,
            "envelopes": [e.para_json() for e in envelopes],
        }


@pytest.fixture
def api():
    app = criar_app("sqlite://")
    with TestClient(app) as cliente:
        cliente.app_state = app.state
        yield cliente


@pytest.fixture
def alice(api):
    return Usuario(api, "alice", rsa_didatico.gerar(32))


@pytest.fixture
def bob(api):
    return Usuario(api, "bob", rsa_didatico.gerar(32))


@pytest.fixture
def carol(api):
    return Usuario(api, "carol", rsa_didatico.gerar(32))


def _conversa(api, dono, *outros, modo="didatico"):
    resposta = api.post("/api/conversations", json={"participantes": [o.nome for o in outros], "modo": modo}, headers=dono.headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _pub(*usuarios, modo="didatico"):
    return {u.nome: u.privadas[modo].publica for u in usuarios}


# ---------------------------------------------------------------- conversas


def test_conversa_1a1_nao_duplica(api, alice, bob):
    primeira = _conversa(api, alice, bob)
    assert primeira["tipo"] == "1:1" and primeira["participantes"] == ["alice", "bob"]
    assert _conversa(api, bob, alice)["id"] == primeira["id"]
    assert _conversa(api, alice, bob, modo="real")["id"] != primeira["id"]  # outro modo, outra conversa


def test_conversa_em_grupo(api, alice, bob, carol):
    grupo = _conversa(api, alice, bob, carol)
    assert grupo["tipo"] == "grupo" and grupo["participantes"] == ["alice", "bob", "carol"]
    assert [c["id"] for c in api.get("/api/conversations", headers=carol.headers).json()] == [grupo["id"]]


def test_conversa_invalida(api, alice):
    assert api.post("/api/conversations", json={"participantes": ["ninguem"]}, headers=alice.headers).status_code == 404
    assert api.post("/api/conversations", json={"participantes": ["alice"]}, headers=alice.headers).status_code == 422
    assert api.post("/api/conversations", json={"participantes": ["bob"]}).status_code == 401


def test_historico_de_quem_nao_participa(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob)
    assert api.get("/api/messages", params={"conversation_id": conversa["id"]}, headers=carol.headers).status_code == 404


# ---------------------------------------------------------------- canal


def test_token_invalido_fecha_o_canal(api):
    with pytest.raises(WebSocketDisconnect) as erro:
        with api.websocket_connect("/ws?token=inventado") as ws:
            ws.receive_json()
    assert erro.value.code == 4401


def test_a_para_b_online(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
        envio = alice.envio(conversa, "oi bob", _pub(bob))
        ws_a.send_json(envio)
        recebido = ws_b.receive_json()
        assert recebido["type"] == "message"
        assert recebido["envelope"]["to"] == "bob" and recebido["envelope"]["from"] == "alice"
        assert ws_a.receive_json() == {"type": "sent", "message_id": envio["message_id"], "offline": []}

        ws_b.send_json({"type": "ack", "message_id": envio["message_id"]})
        assert ws_a.receive_json() == {"type": "delivered", "message_id": envio["message_id"], "to": "bob"}


def test_criar_conversa_avisa_quem_esta_conectado(api, alice, bob):
    with bob.ws(api) as ws_b:
        conversa = _conversa(api, alice, bob)
        aviso = ws_b.receive_json()
    assert aviso["type"] == "conversation" and aviso["conversation"]["id"] == conversa["id"]


def test_fila_offline(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a:
        envio = alice.envio(conversa, "você estava offline", _pub(bob))
        ws_a.send_json(envio)
        assert ws_a.receive_json()["offline"] == ["bob"]

    with bob.ws(api) as ws_b:
        pendente = ws_b.receive_json()
        assert pendente["type"] == "message" and pendente["envelope"]["message_id"] == envio["message_id"]
        ws_b.send_json({"type": "ack", "message_id": envio["message_id"]})
        ws_b.send_json({"type": "ping"})  # garante que o ack foi processado antes de sair
        assert ws_b.receive_json()["code"] == "unknown_type"

    with api.app_state.sessionmaker() as db:
        status = {r.recipient_id: r.status for r in db.scalars(select(EnvelopeRegistro))}
    assert status == {1: "entregue", 2: "entregue"}  # cópia da alice nasce entregue


def test_grupo_entrega_um_envelope_a_cada_um(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob, carol)["id"]
    with alice.ws(api) as ws_a, bob.ws(api) as ws_b, carol.ws(api) as ws_c:
        ws_a.send_json(alice.envio(conversa, "oi grupo", _pub(bob, carol)))
        assert ws_b.receive_json()["envelope"]["to"] == "bob"
        assert ws_c.receive_json()["envelope"]["to"] == "carol"
        assert ws_a.receive_json()["type"] == "sent"


def test_historico_so_traz_os_proprios_envelopes(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws_a:
        ws_a.send_json(alice.envio(conversa, "um", _pub(bob)))
        ws_a.receive_json()
    params = {"conversation_id": conversa}
    assert [e["to"] for e in api.get("/api/messages", params=params, headers=alice.headers).json()] == ["alice"]
    assert [e["to"] for e in api.get("/api/messages", params=params, headers=bob.headers).json()] == ["bob"]


def _erro(api, usuario, envio):
    with usuario.ws(api) as ws:
        ws.send_json(envio)
        resposta = ws.receive_json()
    assert resposta["type"] == "error"
    return resposta


def test_quem_nao_participa_nao_envia(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob)["id"]
    envio = carol.envio(conversa, "intrusa", _pub(alice, bob))
    assert _erro(api, carol, envio)["code"] == "not_participant"


def test_remetente_falso(api, alice, bob):
    """Alice tenta mandar envelopes que dizem vir de Bob."""
    conversa = _conversa(api, alice, bob)["id"]
    envio = bob.envio(conversa, "sou o bob", _pub(alice))
    assert _erro(api, alice, envio)["code"] == "bad_sender"


def test_falta_a_copia_do_remetente(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    resposta = _erro(api, alice, alice.envio(conversa, "x", _pub(bob), incluir_copia=False))
    assert resposta["code"] == "wrong_recipients" and resposta["participantes"] == ["alice", "bob"]


def test_chave_do_destinatario_desatualizada(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    velha = rsa_didatico.gerar(32).publica  # não é a chave ativa de Bob
    resposta = _erro(api, alice, alice.envio(conversa, "x", {"bob": velha}))
    assert resposta["code"] == "key_outdated"
    assert resposta["chaves"]["bob"]["key_id"] == bob.privadas["didatico"].publica.key_id


def test_assinada_com_chave_que_nao_e_a_ativa(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    alice.privadas["didatico"] = rsa_didatico.gerar(32)  # chave não publicada
    assert _erro(api, alice, alice.envio(conversa, "x", _pub(bob)))["code"] == "sender_key_outdated"


def test_message_id_repetido(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    envio = alice.envio(conversa, "uma vez", _pub(bob))
    with alice.ws(api) as ws:
        ws.send_json(envio)
        assert ws.receive_json()["type"] == "sent"
        ws.send_json(envio)
        assert ws.receive_json()["code"] == "duplicate"


def test_modo_diferente_da_conversa(api, alice, bob):
    conversa = _conversa(api, alice, bob, modo="real")["id"]
    assert _erro(api, alice, alice.envio(conversa, "x", _pub(bob)))["code"] == "wrong_mode"


def test_destinatario_sem_chave_no_modo(api, bob):
    alice = Usuario(api, "alice", rsa_real.gerar())
    conversa = _conversa(api, alice, bob, modo="real")["id"]
    qualquer = rsa_real.gerar().publica
    resposta = _erro(api, alice, alice.envio(conversa, "x", {"bob": qualquer}, modo="real"))
    assert resposta["code"] == "recipient_without_key" and resposta["usuarios"] == ["bob"]


def test_mensagens_invalidas(api, alice):
    with alice.ws(api) as ws:
        ws.send_text("isto não é json")
        assert ws.receive_json()["code"] == "invalid"
        ws.send_json({"type": "send", "message_id": "curto"})
        assert ws.receive_json()["code"] == "invalid"
        ws.send_json({"type": "ack", "message_id": "x"})
        assert ws.receive_json()["code"] == "invalid"


def test_ack_de_quem_nao_e_destinatario(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob)["id"]
    envio = alice.envio(conversa, "para o bob", _pub(bob))
    with alice.ws(api) as ws_a:
        ws_a.send_json(envio)
        ws_a.receive_json()
    with carol.ws(api) as ws_c:
        ws_c.send_json({"type": "ack", "message_id": envio["message_id"]})
        ws_c.send_json({"type": "ping"})
        ws_c.receive_json()
    with api.app_state.sessionmaker() as db:
        envelope_bob = db.scalar(select(EnvelopeRegistro).where(EnvelopeRegistro.recipient_id == 2))
    assert envelope_bob.status == "pendente"


def test_banco_so_tem_cifrado(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with alice.ws(api) as ws:
        ws.send_json(alice.envio(conversa, "texto-claro-secreto", _pub(bob)))
        ws.receive_json()
    with api.app_state.sessionmaker() as db:
        conexao = db.connection().connection
        despejo = "\n".join(
            str(linha)
            for (tabela,) in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for linha in conexao.execute(f"SELECT * FROM {tabela}").fetchall()
        )
    assert "texto-claro-secreto" not in despejo
