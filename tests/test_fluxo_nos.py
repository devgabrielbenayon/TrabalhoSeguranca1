"""Nós, reconexão e Observador de ponta a ponta: servidor uvicorn real + aparelhos com o Mensageiro."""

import pytest
from websockets.exceptions import InvalidStatus

from frontend.mensageiro import Mensageiro
from frontend.observador import ClienteObservador
from tests.conftest import esperar
from tests.test_fluxo_mensagens import _online, _textos, aparelho  # noqa: F401 (fixture)


async def _nos(m: Mensageiro) -> dict[str, int]:
    return {n.nome: n.id for n in await m.sessao.api.servidores()}


async def test_sem_caminho_a_mensagem_espera_e_sai_quando_o_no_volta(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")  # Manaus e São Paulo
    conversa = await alice.nova_conversa(["bob"], "didatico")
    nos = await _nos(alice)
    await alice.sessao.api.status_servidor(nos["Brasília"], False)
    await alice.sessao.api.status_servidor(nos["Recife"], False)

    item = await alice.enviar(conversa.id, "quando der")
    assert (item.status, item.sem_rota, len(item.envelopes)) == ("enviada", {"bob"}, 2)  # bob + cópia
    assert conversa.id not in bob.conversas or not _textos(bob, conversa.id)

    await alice.sessao.api.status_servidor(nos["Recife"], True)
    await esperar(lambda: conversa.id in bob.conversas and _textos(bob, conversa.id) == [("alice", "quando der", "verificada")])
    await esperar(lambda: item.status == "entregue" and not item.sem_rota)
    recebido = bob.conversas[conversa.id].ordenadas()[0]
    assert [e.to for e in recebido.envelopes] == ["bob"]  # o Inspetor de Bob tem o envelope que chegou


async def test_reconecta_sozinho_quando_o_canal_cai(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "didatico")
    await esperar(lambda: conversa.id in bob.conversas)

    await alice._ws.close()  # queda que ninguém pediu (rede, servidor reiniciado…)
    await esperar(lambda: not alice.conectado)
    await esperar(lambda: alice.conectado, segundos=8)

    await bob.enviar(conversa.id, "chegou depois da queda")
    await esperar(lambda: _textos(alice, conversa.id) == [("bob", "chegou depois da queda", "verificada")])


async def test_conta_removida_encerra_a_sessao_do_aparelho(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    await alice.sessao.api.remover_cliente(bob.sessao.usuario.id)
    await esperar(lambda: bob.sessao_expirada, segundos=8)  # o servidor fechou o canal e recusa o token
    assert not bob.conectado and not bob.reconectando


async def test_observador_acompanha_o_caminho(aparelho, servidor):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    assinante = ClienteObservador(alice.sessao, servidor["ws"] + "/observer")
    try:
        await assinante.conectar()
        await esperar(lambda: assinante.topologia is not None)
        assert [n.nome for n in assinante.topologia.nos] == ["Manaus", "São Paulo", "Brasília", "Recife"]

        conversa = await bob.nova_conversa(["alice"], "didatico")
        await bob.enviar(conversa.id, "observe")
        await esperar(lambda: assinante.recentes({"transito"}))
        transito = assinante.recentes({"transito"})[0]
        assert (transito["de"], transito["para"], transito["caminho"]) == ("bob", "alice", ["São Paulo", "Brasília", "Manaus"])
        assert assinante.evento(transito["message_id"], "alice") is transito
        await esperar(lambda: assinante.recentes({"confirmado"}))  # Alice confirmou a entrega
    finally:
        await assinante.desconectar()


async def test_quem_nao_e_administrador_nao_assina_o_observador(aparelho, servidor):
    await _online(aparelho, "alice")
    bob = await _online(aparelho, "bob")
    assinante = ClienteObservador(bob.sessao, servidor["ws"] + "/observer")
    with pytest.raises(InvalidStatus) as erro:  # recusado antes do aceite: o handshake vira HTTP 403
        await assinante.conectar()
    assert erro.value.response.status_code == 403
    assert assinante.topologia is None
