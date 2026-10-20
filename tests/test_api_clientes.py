"""CRUD de clientes (RF12) direto na API: listar, editar, remover (revoga chaves e derruba sessões) e reativar."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import criar_app
from shared.crypto import rsa_didatico
from tests.test_api_relay import Usuario, _conversa, _pub


@pytest.fixture
def api():
    app = criar_app("sqlite://")
    with TestClient(app) as cliente:
        cliente.app_state = app.state
        yield cliente


@pytest.fixture
def alice(api):  # primeiro cadastro: administradora
    return Usuario(api, "alice", rsa_didatico.gerar(32))


@pytest.fixture
def bob(api):
    return Usuario(api, "bob", rsa_didatico.gerar(32))


@pytest.fixture
def carol(api):
    return Usuario(api, "carol", rsa_didatico.gerar(32))


def _id(api, usuario) -> int:
    return api.get("/api/me", headers=usuario.headers).json()["id"]


def _nos(api, usuario) -> dict[str, int]:
    return {n["nome"]: n["id"] for n in api.get("/api/servers", headers=usuario.headers).json()}


def _editar(api, quem, alvo, **campos):
    return api.put(f"/api/clients/{_id(api, alvo)}", json=campos, headers=quem.headers)


def _remover(api, quem, alvo_id, senha=None):
    return api.request("DELETE", f"/api/clients/{alvo_id}", json={"senha": senha} if senha else None, headers=quem.headers)


def test_listar_clientes(api, alice, bob):
    assert api.get("/api/clients").status_code == 401
    lista = api.get("/api/clients", headers=bob.headers).json()
    assert [c["username"] for c in lista] == ["alice", "bob"]
    assert (lista[0]["is_admin"], lista[0]["servidor"], lista[0]["modos_ativos"], lista[0]["online"]) == (True, "Manaus", ["didatico"], False)
    with bob.ws(api):
        detalhe = api.get(f"/api/clients/{_id(api, bob)}", headers=alice.headers).json()
        assert detalhe["online"] is True and detalhe["servidor"] == "São Paulo"
    assert api.get("/api/clients/999", headers=alice.headers).status_code == 404


def test_cada_um_edita_o_proprio_perfil(api, alice, bob):
    resposta = _editar(api, bob, bob, nome="Roberto", avatar="🐢")
    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["nome"], resposta.json()["avatar"]) == ("Roberto", "🐢")
    assert _editar(api, bob, bob, avatar=None).json()["avatar"] is None  # null apaga o avatar
    assert _editar(api, bob, bob, nome=None).json()["nome"] == "Roberto"  # null nos outros campos não muda nada

    assert _editar(api, bob, alice, nome="Hackeada").status_code == 403
    assert _editar(api, bob, bob, server_id=_nos(api, bob)["Manaus"]).status_code == 403
    assert _editar(api, bob, bob, is_admin=True).status_code == 403
    assert _editar(api, bob, bob, nome="").status_code == 422


def test_administrador_muda_o_no_e_promove(api, alice, bob):
    nos = _nos(api, alice)
    resposta = _editar(api, alice, bob, server_id=nos["Manaus"], is_admin=True)
    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["servidor"], resposta.json()["is_admin"]) == ("Manaus", True)

    api.patch(f"/api/servers/{nos['Recife']}/status", json={"ativo": False}, headers=alice.headers)
    assert _editar(api, alice, bob, server_id=nos["Recife"]).status_code == 409  # nó desligado
    assert _editar(api, alice, bob, server_id=999).status_code == 404


def test_o_ultimo_administrador_nao_sai(api, alice, bob):
    assert _editar(api, alice, alice, is_admin=False).status_code == 409
    assert _remover(api, alice, _id(api, alice), senha="segredo123").status_code == 409
    _editar(api, alice, bob, is_admin=True)
    assert _editar(api, alice, alice, is_admin=False).json()["is_admin"] is False


def test_administrador_remove_um_cliente(api, alice, bob, carol):
    conversa = _conversa(api, alice, bob)["id"]
    id_bob = _id(api, bob)
    with alice.ws(api) as ws_a, bob.ws(api) as ws_b:
        assert _remover(api, carol, id_bob).status_code == 403  # quem não é administrador não remove os outros
        assert _remover(api, alice, id_bob).status_code == 204
        assert ws_a.receive_json() == {"type": "key_revoked", "user": "bob", "modo": "didatico", "key_id": bob.privadas["didatico"].publica.key_id}
        with pytest.raises(WebSocketDisconnect):  # o canal de Bob foi fechado
            ws_b.receive_json()
        ws_a.send_json(alice.envio(conversa, "ainda está aí?", _pub(bob)))
        assert ws_a.receive_json()["code"] == "recipient_without_key"

    assert api.get("/api/me", headers=bob.headers).status_code == 401  # todas as sessões caíram
    assert api.post("/api/auth/login", json={"username": "bob", "senha": "segredo123"}).status_code == 401
    assert "bob" not in [c["username"] for c in api.get("/api/clients", headers=carol.headers).json()]
    removido = next(c for c in api.get("/api/clients", headers=alice.headers).json() if c["username"] == "bob")
    assert (removido["ativo"], removido["modos_ativos"]) == (False, [])
    assert api.get("/api/keys", params={"users": "bob", "modo": "didatico"}, headers=alice.headers).json()["sem_chave"] == ["bob"]
    assert _remover(api, alice, id_bob).status_code == 409  # já removido


def test_remover_a_propria_conta_pede_a_senha(api, alice, bob):
    id_bob = _id(api, bob)
    assert _remover(api, bob, id_bob).status_code == 403
    assert _remover(api, bob, id_bob, senha="errada").status_code == 403
    assert _remover(api, bob, id_bob, senha="segredo123").status_code == 204
    assert api.get("/api/me", headers=bob.headers).status_code == 401


def test_reativar_um_cliente_removido(api, alice, bob, carol):
    id_bob = _id(api, bob)
    _remover(api, alice, id_bob)
    assert api.put(f"/api/clients/{id_bob}", json={"ativo": True}, headers=carol.headers).status_code == 404  # nem vê
    assert api.put(f"/api/clients/{id_bob}", json={"ativo": False}, headers=alice.headers).status_code == 422  # remover é DELETE
    reativado = api.put(f"/api/clients/{id_bob}", json={"ativo": True}, headers=alice.headers).json()
    assert (reativado["ativo"], reativado["modos_ativos"], reativado["servidor"]) == (True, [], "São Paulo")
    assert api.post("/api/auth/login", json={"username": "bob", "senha": "segredo123"}).status_code == 200
