"""Fluxos 5.4 (troca) e 5.5 (exclusão) de ponta a ponta: servidor real + aparelhos."""

import pytest

from frontend.api_client import ApiCliente, ErroApi
from frontend.mensageiro import ErroEnvio, Mensageiro
from frontend.sessao import Sessao
from tests.conftest import esperar
from tests.test_fluxo_mensagens import _online, _textos, aparelho  # noqa: F401 (fixture)


def _avisos(m: Mensageiro, conversa_id: int) -> list[str]:
    return [i.texto for i in m.conversas[conversa_id].ordenadas() if i.status == "aviso"]


def _mensagens(m: Mensageiro, conversa_id: int) -> list[tuple[str, str | None, str]]:
    return [t for t in _textos(m, conversa_id) if t[0] != "sistema"]


async def _reabrir(servidor, m: Mensageiro, senha="segredo123") -> Mensageiro:
    novo = Mensageiro(Sessao(ApiCliente(servidor["http"]), m.sessao.raiz_keystore), servidor["ws"])
    await novo.sessao.entrar(m.eu, senha)
    await novo.conectar()
    return novo


async def _fechar(m: Mensageiro) -> None:
    await m.desconectar()
    await m.sessao.api.fechar()


async def test_troca_avisa_e_mantem_o_historico(aparelho, servidor):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await bob.nova_conversa(["alice"], "real")
    await bob.enviar(conversa.id, "m1 para a chave antiga")
    await esperar(lambda: conversa.id in alice.conversas and _mensagens(alice, conversa.id))
    antiga = alice.sessao.keystore.ativa("real").publica.key_id

    nova, _ = await alice.sessao.trocar_chave("real")
    assert nova.key_id != antiga
    await esperar(lambda: any("A chave de alice mudou" in a for a in _avisos(bob, conversa.id)))
    assert not _avisos(alice, conversa.id)  # a própria troca não gera alerta para quem trocou

    await bob.enviar(conversa.id, "m2 para a chave nova")  # cache invalidado: busca a chave nova
    await alice.enviar(conversa.id, "m3 assinada com a chave nova")
    esperado = [
        ("bob", "m1 para a chave antiga", "verificada"),
        ("bob", "m2 para a chave nova", "verificada"),
        ("alice", "m3 assinada com a chave nova", "verificada"),
    ]
    await esperar(lambda: [(r, t) for r, t, _ in _mensagens(alice, conversa.id)] == [(r, t) for r, t, _ in esperado])
    await esperar(lambda: _mensagens(bob, conversa.id)[-1] == esperado[-1])

    # Alice reabre o app: m1 usa a privada antiga (mantida no keystore), m2 e m3 a nova
    reaberta = await _reabrir(servidor, alice)
    try:
        assert [t for _, t, _ in _mensagens(reaberta, conversa.id)] == [t for _, t, _ in esperado]
        assert all(s in ("verificada", "enviada") for _, _, s in _mensagens(reaberta, conversa.id))
    finally:
        await _fechar(reaberta)


async def test_contato_offline_e_avisado_quando_volta(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await bob.nova_conversa(["alice"], "real")
    await bob.enviar(conversa.id, "oi")  # bob conhece (e guarda) o fingerprint de alice
    await bob.desconectar()

    await alice.sessao.trocar_chave("real")  # bob não está conectado para receber o aviso

    await bob.conectar()
    await bob.enviar(conversa.id, "você mudou alguma coisa?")
    assert any("A chave de alice mudou" in a for a in _avisos(bob, conversa.id))
    await esperar(lambda: _mensagens(alice, conversa.id)[-1][1] == "você mudou alguma coisa?")


async def test_exclusao_e_nova_publicacao(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await bob.nova_conversa(["alice"], "didatico")
    await bob.enviar(conversa.id, "antes")
    await esperar(lambda: conversa.id in alice.conversas and _mensagens(alice, conversa.id))

    await alice.sessao.excluir_chave("didatico", "segredo123")
    await esperar(lambda: any("alice excluiu a chave" in a for a in _avisos(bob, conversa.id)))
    with pytest.raises(ErroEnvio) as erro:
        await bob.enviar(conversa.id, "alguém aí?")
    assert "alice" in erro.value.detail
    with pytest.raises(ErroEnvio):
        await alice.enviar(conversa.id, "sem chave ativa não assino")

    await alice.sessao.trocar_chave("didatico")  # publica de novo
    await esperar(lambda: any("A chave de alice mudou" in a for a in _avisos(bob, conversa.id)))
    await bob.enviar(conversa.id, "bem-vinda de volta")
    await esperar(lambda: [t for _, t, _ in _mensagens(alice, conversa.id)] == ["antes", "bem-vinda de volta"])


async def test_apagar_privadas_deixa_o_historico_ilegivel(aparelho, servidor):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await bob.nova_conversa(["alice"], "real")
    await bob.enviar(conversa.id, "segredo do passado")
    await esperar(lambda: conversa.id in alice.conversas and _mensagens(alice, conversa.id))

    await alice.sessao.excluir_chave("real", "segredo123", apagar_privadas=True)
    reaberta = await _reabrir(servidor, alice)
    try:
        [(remetente, texto, status)] = _mensagens(reaberta, conversa.id)
        assert (remetente, texto, status) == ("bob", None, "rejeitada")
        item = reaberta.conversas[conversa.id].ordenadas()[0]
        assert "não está neste aparelho" in item.erro
    finally:
        await _fechar(reaberta)


async def test_senha_errada_nao_exclui(aparelho):
    alice = await _online(aparelho, "alice")
    with pytest.raises(ErroApi) as erro:
        await alice.sessao.excluir_chave("real", "errada")
    assert erro.value.status == 403
    assert alice.sessao.keystore.ativa("real") is not None
