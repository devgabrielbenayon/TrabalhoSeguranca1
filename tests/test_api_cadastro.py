"""Passo 0 (cadastro com prova de posse), login e diretório de chaves — direto na API."""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import criar_app
from backend.models import KeyAccess, KeyEvent
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.prova import mensagem_prova


@pytest.fixture(scope="module")
def chaves_reais():
    """Gerar RSA-2048 é lento: um par por usuário de teste, reaproveitado."""
    return {nome: rsa_real.gerar() for nome in ("alice", "bob", "carol")}


@pytest.fixture
def api():
    app = criar_app("sqlite://")
    with TestClient(app) as cliente:
        cliente.app_state = app.state
        yield cliente


def _chave(privada, username, acao="registro", assinante=None):
    assinante = assinante or privada
    prova = assinante.assinar(mensagem_prova(acao, username, privada.publica.key_id))
    return {"modo": privada.modo, "public_key": privada.publica.exportar(), "prova": base64.b64encode(prova).decode()}


def _registrar(api, username, *privadas, senha="segredo123"):
    return api.post(
        "/api/auth/register",
        json={"username": username, "nome": username.title(), "senha": senha, "chaves": [_chave(p, username) for p in privadas]},
    )


def _login(api, username, senha="segredo123"):
    resposta = api.post("/api/auth/login", json={"username": username, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['token']}"}


def test_cadastro_com_os_dois_modos(api, chaves_reais):
    didatica = rsa_didatico.gerar(32)
    resposta = _registrar(api, "alice", chaves_reais["alice"], didatica)
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["usuario"]["is_admin"] is True  # primeiro usuário
    assert {c["key_id"] for c in corpo["chaves"]} == {chaves_reais["alice"].publica.key_id, didatica.publica.key_id}
    assert all(c["status"] == "ativa" for c in corpo["chaves"])

    resposta = _registrar(api, "bob", chaves_reais["bob"])
    assert resposta.json()["usuario"]["is_admin"] is False


def test_username_repetido(api, chaves_reais):
    assert _registrar(api, "alice", chaves_reais["alice"]).status_code == 201
    assert _registrar(api, "alice", chaves_reais["bob"]).status_code == 409


def test_mesma_chave_publica_em_dois_usuarios(api, chaves_reais):
    assert _registrar(api, "alice", chaves_reais["alice"]).status_code == 201
    corpo = {"username": "bob", "nome": "Bob", "senha": "segredo123", "chaves": [_chave(chaves_reais["alice"], "bob")]}
    assert api.post("/api/auth/register", json=corpo).status_code == 409


def test_prova_de_posse_assinada_por_outra_chave(api, chaves_reais):
    """Mallory tenta publicar a pública de Bob sem ter a privada dele."""
    chave = _chave(chaves_reais["bob"], "mallory", assinante=chaves_reais["carol"])
    resposta = api.post("/api/auth/register", json={"username": "mallory", "nome": "M", "senha": "segredo123", "chaves": [chave]})
    assert resposta.status_code == 400
    assert "prova de posse" in resposta.json()["detail"]


def test_prova_de_outro_username_nao_vale(api, chaves_reais):
    chave = _chave(chaves_reais["alice"], "alice")
    resposta = api.post("/api/auth/register", json={"username": "eve", "nome": "E", "senha": "segredo123", "chaves": [chave]})
    assert resposta.status_code == 400


def test_chave_real_pequena_e_recusada(api):
    resposta = _registrar(api, "alice", rsa_real.gerar(1024))
    assert resposta.status_code == 422


def test_modo_declarado_diferente_da_chave(api, chaves_reais):
    chave = _chave(chaves_reais["alice"], "alice") | {"modo": "didatico"}
    resposta = api.post("/api/auth/register", json={"username": "alice", "nome": "A", "senha": "segredo123", "chaves": [chave]})
    assert resposta.status_code == 422


def test_duas_chaves_do_mesmo_modo(api, chaves_reais):
    chaves = [_chave(chaves_reais["alice"], "alice"), _chave(chaves_reais["bob"], "alice")]
    resposta = api.post("/api/auth/register", json={"username": "alice", "nome": "A", "senha": "segredo123", "chaves": chaves})
    assert resposta.status_code == 422


@pytest.mark.parametrize("username", ["Al", "ALICE", "a lice", "x" * 21])
def test_username_invalido(api, chaves_reais, username):
    assert _registrar(api, username, chaves_reais["alice"]).status_code == 422


def test_login_e_rotas_protegidas(api, chaves_reais):
    _registrar(api, "alice", chaves_reais["alice"])
    assert api.get("/api/me").status_code == 401
    assert api.get("/api/me", headers={"Authorization": "Bearer inventado"}).status_code == 401
    assert api.post("/api/auth/login", json={"username": "alice", "senha": "errada"}).status_code == 401
    assert api.post("/api/auth/login", json={"username": "ninguem", "senha": "segredo123"}).status_code == 401

    headers = _login(api, "alice")
    assert api.get("/api/me", headers=headers).json()["username"] == "alice"

    assert api.post("/api/auth/logout", headers=headers).status_code == 204
    assert api.get("/api/me", headers=headers).status_code == 401


def test_diretorio_de_chaves(api, chaves_reais):
    for nome in ("alice", "bob", "carol"):
        _registrar(api, nome, chaves_reais[nome], rsa_didatico.gerar(24))
    headers = _login(api, "alice")

    assert api.get("/api/keys", params={"users": "bob"}).status_code == 401

    resposta = api.get("/api/keys", params={"users": "bob,carol,ninguem,bob"}, headers=headers).json()
    assert set(resposta["chaves"]) == {"bob", "carol"}
    assert resposta["sem_chave"] == ["ninguem"]
    assert resposta["chaves"]["bob"]["key_id"] == chaves_reais["bob"].publica.key_id
    assert resposta["chaves"]["bob"]["fingerprint"] == chaves_reais["bob"].publica.fingerprint

    didaticas = api.get("/api/keys", params={"users": "bob", "modo": "didatico"}, headers=headers).json()
    assert didaticas["chaves"]["bob"]["modo"] == "didatico"


def test_diretorio_registra_quem_buscou(api, chaves_reais):
    for nome in ("alice", "bob"):
        _registrar(api, nome, chaves_reais[nome])
    headers = _login(api, "alice")
    api.get("/api/keys", params={"users": "bob,alice"}, headers=headers)
    api.get("/api/keys", params={"users": "bob"}, headers=headers)

    with api.app_state.sessionmaker() as db:
        acessos = db.scalars(select(KeyAccess)).all()
        assert [(a.client_id, a.owner_id) for a in acessos] == [(1, 2)]  # sem duplicar e sem registrar a si mesmo
        assert {e.tipo for e in db.scalars(select(KeyEvent))} == {"criada"}


def test_minhas_chaves(api, chaves_reais):
    _registrar(api, "alice", chaves_reais["alice"], rsa_didatico.gerar(32))
    chaves = api.get("/api/me/keys", headers=_login(api, "alice")).json()
    assert sorted(c["modo"] for c in chaves) == ["didatico", "real"]


def test_banco_nao_tem_privada_nem_senha(api, chaves_reais):
    didatica = rsa_didatico.gerar(64)
    _registrar(api, "alice", chaves_reais["alice"], didatica, senha="senha-em-claro")
    with api.app_state.sessionmaker() as db:
        conexao = db.connection().connection
        linhas = []
        for (tabela,) in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            linhas += [str(linha) for linha in conexao.execute(f"SELECT * FROM {tabela}").fetchall()]
    despejo = "\n".join(linhas)
    assert "PRIVATE KEY" not in despejo
    assert str(didatica.d) not in despejo
    assert "senha-em-claro" not in despejo
