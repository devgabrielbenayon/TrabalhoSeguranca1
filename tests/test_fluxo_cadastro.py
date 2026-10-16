"""Fluxo 5.1 de ponta a ponta: app cliente (Sessao) falando com o back-end real, em memória.

Todo o tráfego HTTP é capturado para provar que nenhuma chave privada sai do cliente.
"""

import httpx
import pytest

from backend.main import criar_app
from frontend.api_client import ApiCliente, ErroApi
from frontend.sessao import Sessao


@pytest.fixture
def trafego():
    return []


@pytest.fixture
async def novo_aparelho(tmp_path, trafego):
    app = criar_app("sqlite://")
    abertos = []

    async def capturar(requisicao: httpx.Request):
        trafego.append(requisicao.content.decode("utf-8", "replace") + str(requisicao.url))

    def fabricar(nome: str) -> Sessao:
        api = ApiCliente("http://teste", transport=httpx.ASGITransport(app=app), event_hooks={"request": [capturar]})
        abertos.append(api)
        return Sessao(api, tmp_path / nome)

    yield fabricar
    for api in abertos:
        await api.fechar()


async def test_cadastro_publica_so_a_publica(novo_aparelho, trafego):
    alice = novo_aparelho("aparelho-alice")
    registro, geracao = await alice.cadastrar("Alice", "Alice", "segredo123", bits_didatico=48)

    assert alice.logado and alice.usuario.username == "alice"
    real, didatica = alice.keystore.ativa("real"), alice.keystore.ativa("didatico")
    assert {c.key_id for c in registro.chaves} == {real.publica.key_id, didatica.publica.key_id}
    assert (didatica.publica.e, didatica.publica.n, didatica.d) == (geracao.e, geracao.n, geracao.d)

    tudo = "\n".join(trafego)
    assert "PRIVATE KEY" not in tudo
    assert str(geracao.d) not in tudo and str(geracao.p) not in tudo and str(geracao.q) not in tudo


async def test_rastro_da_geracao(novo_aparelho):
    alice = novo_aparelho("a")
    await alice.cadastrar("alice", "Alice", "segredo123")
    eventos = alice.tracer.eventos
    assert [e.etapa for e in eventos] == ["geracao_chaves", "geracao_chaves", "prova_de_posse"]
    assert all(e.ator == "alice" for e in eventos)
    assert {"p", "q", "phi", "e", "d", "n"} <= eventos[0].detalhes.keys()


async def test_outro_aparelho_busca_a_chave(novo_aparelho):
    alice, bob = novo_aparelho("a"), novo_aparelho("b")
    await alice.cadastrar("alice", "Alice", "segredo123")
    await bob.cadastrar("bob", "Bob", "segredo456")

    diretorio = await alice.api.buscar_chaves(["bob"])
    assert diretorio.chaves["bob"].key_id == bob.keystore.ativa("real").publica.key_id


async def test_login_em_aparelho_sem_as_chaves(novo_aparelho):
    await novo_aparelho("a").cadastrar("alice", "Alice", "segredo123")
    outro = novo_aparelho("outro")
    assert await outro.entrar("alice", "segredo123") is False
    assert outro.logado


async def test_cadastro_repetido_nao_grava_keystore(novo_aparelho):
    await novo_aparelho("a").cadastrar("alice", "Alice", "segredo123")
    intruso = novo_aparelho("b")
    with pytest.raises(ErroApi) as erro:
        await intruso.cadastrar("alice", "Outra", "segredo999")
    assert erro.value.status == 409
    assert not (intruso.raiz_keystore / "alice").exists()


async def test_sair(novo_aparelho):
    alice = novo_aparelho("a")
    await alice.cadastrar("alice", "Alice", "segredo123")
    await alice.sair()
    assert not alice.logado
    with pytest.raises(ErroApi):
        await alice.api.eu()
