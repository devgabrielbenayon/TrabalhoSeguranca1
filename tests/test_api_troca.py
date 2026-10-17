"""Fluxos 5.4 (troca) e 5.5 (exclusão) direto na API, com chaves didáticas."""

import base64
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import criar_app
from backend.models import KeyChallenge, KeyEvent
from shared.crypto import rsa_didatico
from shared.crypto.prova import mensagem_prova
from tests.test_api_relay import Usuario, _conversa, _pub


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


def _nonce(api, usuario):
    resposta = api.post("/api/keys/challenge", headers=usuario.headers)
    assert resposta.status_code == 200
    return resposta.json()["nonce"]


def _trocar(api, usuario, nova, nonce=None, assinante=None, username=None):
    nonce = nonce or _nonce(api, usuario)
    assinante = assinante or nova
    prova = assinante.assinar(mensagem_prova("troca", username or usuario.nome, nova.publica.key_id, nonce))
    corpo = {"modo": nova.modo, "public_key": nova.publica.exportar(), "nonce": nonce, "prova": base64.b64encode(prova).decode()}
    return api.put("/api/me/key", json=corpo, headers=usuario.headers)


def _status_das_chaves(api, usuario):
    return {c["key_id"]: c["status"] for c in api.get("/api/me/keys", headers=usuario.headers).json()}


# ---------------------------------------------------------------- troca


def test_troca(api, alice, bob):
    antiga = alice.privadas["didatico"]
    nova = rsa_didatico.gerar(32)
    resposta = _trocar(api, alice, nova)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["key_id"] == nova.publica.key_id

    assert _status_das_chaves(api, alice) == {antiga.publica.key_id: "substituida", nova.publica.key_id: "ativa"}
    diretorio = api.get("/api/keys", params={"users": "alice", "modo": "didatico"}, headers=bob.headers).json()
    assert diretorio["chaves"]["alice"]["key_id"] == nova.publica.key_id
    # a antiga continua consultável por key_id: serve para verificar mensagens antigas
    velha = api.get(f"/api/keys/id/{antiga.publica.key_id}", headers=bob.headers).json()
    assert velha["status"] == "substituida"

    with api.app_state.sessionmaker() as db:
        assert [e.tipo for e in db.scalars(select(KeyEvent).where(KeyEvent.client_id == 1))] == ["criada", "substituida", "criada"]


def test_troca_exige_token(api, alice):
    assert api.post("/api/keys/challenge").status_code == 401
    assert api.put("/api/me/key", json={}).status_code == 401


def test_nonce_so_vale_uma_vez(api, alice):
    nonce = _nonce(api, alice)
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=nonce).status_code == 200
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=nonce).status_code == 400


def test_nonce_de_outro_usuario(api, alice, bob):
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=_nonce(api, bob)).status_code == 400


def test_nonce_expirado(api, alice):
    nonce = _nonce(api, alice)
    with api.app_state.sessionmaker() as db:
        desafio = db.get(KeyChallenge, nonce)
        desafio.expira_em -= timedelta(minutes=5)
        db.commit()
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=nonce).status_code == 400


def test_prova_assinada_com_outra_chave(api, alice):
    """Quem tem só o token (sem a nova privada) não consegue publicar uma chave em nome de Alice."""
    nova = rsa_didatico.gerar(32)
    resposta = _trocar(api, alice, nova, assinante=alice.privadas["didatico"])
    assert resposta.status_code == 400
    assert alice.privadas["didatico"].publica.key_id in _status_das_chaves(api, alice)
    assert _status_das_chaves(api, alice)[alice.privadas["didatico"].publica.key_id] == "ativa"


def test_prova_de_outra_acao_nao_vale(api, alice):
    nova = rsa_didatico.gerar(32)
    nonce = _nonce(api, alice)
    prova = nova.assinar(mensagem_prova("registro", "alice", nova.publica.key_id, nonce))
    corpo = {"modo": "didatico", "public_key": nova.publica.exportar(), "nonce": nonce, "prova": base64.b64encode(prova).decode()}
    assert api.put("/api/me/key", json=corpo, headers=alice.headers).status_code == 400


def test_nonce_falho_queima(api, alice):
    nonce = _nonce(api, alice)
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=nonce, assinante=rsa_didatico.gerar(32)).status_code == 400
    assert _trocar(api, alice, rsa_didatico.gerar(32), nonce=nonce).status_code == 400


def test_troca_avisa_quem_tem_a_chave(api, alice, bob, carol):
    api.get("/api/keys", params={"users": "alice", "modo": "didatico"}, headers=bob.headers)  # bob tem em cache
    with bob.ws(api) as ws_b, carol.ws(api) as ws_c:
        nova = rsa_didatico.gerar(32)
        assert _trocar(api, alice, nova).status_code == 200
        aviso = ws_b.receive_json()
        assert aviso == {
            "type": "key_changed", "user": "alice", "modo": "didatico",
            "key_id": nova.publica.key_id, "fingerprint": nova.publica.fingerprint,
        }
        ws_c.send_json({"type": "ping"})  # carol nunca buscou a chave: a primeira coisa que recebe é a resposta ao ping
        assert ws_c.receive_json()["code"] == "unknown_type"


def test_troca_avisa_quem_conversa(api, alice, bob):
    _conversa(api, alice, bob)
    with bob.ws(api) as ws_b:
        assert _trocar(api, alice, rsa_didatico.gerar(32)).status_code == 200
        assert ws_b.receive_json()["type"] == "key_changed"


def test_envio_com_a_chave_antiga_depois_da_troca(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    antiga_bob = bob.privadas["didatico"].publica
    nova = rsa_didatico.gerar(32)
    _trocar(api, bob, nova)
    with alice.ws(api) as ws:
        ws.send_json(alice.envio(conversa, "x", {"bob": antiga_bob}))
        resposta = ws.receive_json()
    assert resposta["code"] == "key_outdated" and resposta["chaves"]["bob"]["key_id"] == nova.publica.key_id


# ---------------------------------------------------------------- exclusão


def test_exclusao(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    with bob.ws(api) as ws_b:
        resposta = api.post("/api/me/key/revoke", json={"modo": "didatico", "senha": "segredo123"}, headers=alice.headers)
        assert resposta.status_code == 204
        aviso = ws_b.receive_json()
        assert aviso["type"] == "key_revoked" and aviso["user"] == "alice"

        diretorio = api.get("/api/keys", params={"users": "alice", "modo": "didatico"}, headers=bob.headers).json()
        assert diretorio["sem_chave"] == ["alice"]

        ws_b.send_json(bob.envio(conversa, "ainda está aí?", _pub(alice)))
        assert ws_b.receive_json()["code"] == "recipient_without_key"

    assert set(_status_das_chaves(api, alice).values()) == {"revogada"}


def test_exclusao_exige_senha(api, alice):
    resposta = api.post("/api/me/key/revoke", json={"modo": "didatico", "senha": "errada"}, headers=alice.headers)
    assert resposta.status_code == 403
    assert api.post("/api/me/key/revoke", json={"modo": "didatico", "senha": "segredo123"}).status_code == 401


def test_exclusao_sem_chave_ativa(api, alice):
    assert api.post("/api/me/key/revoke", json={"modo": "real", "senha": "segredo123"}, headers=alice.headers).status_code == 404


def test_quem_excluiu_nao_envia_mais(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    api.post("/api/me/key/revoke", json={"modo": "didatico", "senha": "segredo123"}, headers=alice.headers)
    with alice.ws(api) as ws:
        ws.send_json(alice.envio(conversa, "x", _pub(bob)))
        assert ws.receive_json()["code"] == "sender_key_outdated"


def test_publicar_de_novo_depois_da_exclusao(api, alice, bob):
    conversa = _conversa(api, alice, bob)["id"]
    api.post("/api/me/key/revoke", json={"modo": "didatico", "senha": "segredo123"}, headers=alice.headers)
    nova = rsa_didatico.gerar(32)
    assert _trocar(api, alice, nova).status_code == 200
    alice.privadas["didatico"] = nova
    with alice.ws(api) as ws:
        ws.send_json(alice.envio(conversa, "voltei", _pub(bob)))
        assert ws.receive_json()["type"] == "sent"
