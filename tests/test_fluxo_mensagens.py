"""Fluxos 5.2 (A → B) e 5.3 (A → B e C) de ponta a ponta: servidor uvicorn real + aparelhos com o Mensageiro."""

import base64

import pytest

from frontend.api_client import ApiCliente
from frontend.mensageiro import Mensageiro
from frontend.sessao import Sessao
from shared.crypto import rsa_real
from shared.crypto.envelope import montar_envelopes
from shared.schemas import ChavePublicaOut
from tests.conftest import esperar


@pytest.fixture
async def aparelho(servidor, tmp_path):
    criados: list[Mensageiro] = []

    def fabricar(nome: str) -> Mensageiro:
        sessao = Sessao(ApiCliente(servidor["http"]), tmp_path / f"aparelho-{nome}")
        mensageiro = Mensageiro(sessao, servidor["ws"])
        criados.append(mensageiro)
        return mensageiro

    yield fabricar
    for m in criados:
        await m.desconectar()
        await m.sessao.api.fechar()


async def _online(aparelho, nome) -> Mensageiro:
    m = aparelho(nome)
    await m.sessao.cadastrar(nome, nome.title(), "segredo123", bits_didatico=32)
    await m.conectar()
    return m


def _textos(m: Mensageiro, conversa_id: int) -> list[tuple[str, str | None, str]]:
    return [(i.remetente, i.texto, i.status) for i in m.conversas[conversa_id].ordenadas()]


@pytest.mark.parametrize("modo", ["real", "didatico"])
async def test_a_para_b_online(aparelho, modo):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], modo)
    await esperar(lambda: conversa.id in bob.conversas)  # aviso de conversa nova pelo WebSocket

    item = await alice.enviar(conversa.id, "Olá, Bob! Ação ✓")
    await esperar(lambda: _textos(bob, conversa.id) == [("alice", "Olá, Bob! Ação ✓", "verificada")])
    await esperar(lambda: item.status == "entregue")


async def test_b_offline_recebe_ao_conectar(aparelho):
    alice = await _online(aparelho, "alice")
    bob = aparelho("bob")
    await bob.sessao.cadastrar("bob", "Bob", "segredo123")

    conversa = await alice.nova_conversa(["bob"], "real")
    item = await alice.enviar(conversa.id, "chegou enquanto você dormia")
    assert item.status == "enviada" and item.aguardando == {"bob"}

    await bob.conectar()
    await esperar(lambda: _textos(bob, conversa.id) == [("alice", "chegou enquanto você dormia", "verificada")])
    await esperar(lambda: item.status == "entregue")


async def test_a_para_b_e_c(aparelho):
    alice, bob, carol = [await _online(aparelho, n) for n in ("alice", "bob", "carol")]
    conversa = await alice.nova_conversa(["bob", "carol"], "real")
    await esperar(lambda: conversa.id in bob.conversas and conversa.id in carol.conversas)

    item = await alice.enviar(conversa.id, "oi grupo")
    for m in (bob, carol):
        await esperar(lambda m=m: _textos(m, conversa.id) == [("alice", "oi grupo", "verificada")])
    await esperar(lambda: item.status == "entregue")

    await bob.enviar(conversa.id, "oi alice e carol")
    await esperar(lambda: [t for _, t, _ in _textos(carol, conversa.id)] == ["oi grupo", "oi alice e carol"])


async def test_copia_do_remetente_no_historico(aparelho, servidor, tmp_path):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "real")
    await alice.enviar(conversa.id, "minha mensagem")
    await esperar(lambda: _textos(bob, conversa.id))
    await bob.enviar(conversa.id, "resposta do bob")

    # Alice fecha o app e abre de novo no mesmo aparelho: tudo vem do servidor, cifrado
    reaberto = Mensageiro(Sessao(ApiCliente(servidor["http"]), alice.sessao.raiz_keystore), servidor["ws"])
    try:
        await reaberto.sessao.entrar("alice", "segredo123")
        await reaberto.conectar()
        assert [(r, t) for r, t, _ in _textos(reaberto, conversa.id)] == [
            ("alice", "minha mensagem"),
            ("bob", "resposta do bob"),
        ]
    finally:
        await reaberto.desconectar()
        await reaberto.sessao.api.fechar()


async def test_cache_de_chaves(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "real")
    for texto in ("um", "dois", "três"):
        await alice.enviar(conversa.id, texto)
    assert alice.cache.buscas == 1


async def test_chave_desatualizada_no_cache_e_recifrada(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "real")

    velha = rsa_real.gerar().publica  # simula uma chave de Bob que já foi trocada
    alice.cache.guardar("bob", ChavePublicaOut(
        username="bob", modo="real", key_id=velha.key_id, public_key=velha.exportar(),
        fingerprint=velha.fingerprint, status="ativa", criada_em="2026-01-01T00:00:00",
    ))
    item = await alice.enviar(conversa.id, "depois da troca")
    assert item.status in ("enviada", "entregue")
    await esperar(lambda: _textos(bob, conversa.id) == [("alice", "depois da troca", "verificada")])


async def test_envelope_adulterado_e_rejeitado(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "real")
    privada = alice.sessao.keystore.ativa("real")
    envelopes = montar_envelopes("pague 10", "alice", privada, await alice.cache.obter(["bob"], "real"), conversa.id)
    para_bob = next(e for e in envelopes if e.to == "bob")
    bruto = bytearray(base64.b64decode(para_bob.blocks[0]))
    bruto[0] ^= 0xFF
    para_bob.blocks[0] = base64.b64encode(bytes(bruto)).decode()

    resposta = await alice._requisitar({
        "type": "send", "message_id": para_bob.message_id, "conversation_id": conversa.id,
        "envelopes": [e.para_json() for e in envelopes],
    })
    assert resposta["type"] == "sent"  # o servidor não verifica conteúdo: só repassa
    await esperar(lambda: _textos(bob, conversa.id))
    item = bob.conversas[conversa.id].ordenadas()[0]
    assert item.status == "rejeitada" and item.texto is None and "AssinaturaInvalida" in item.erro


async def test_servidor_nunca_ve_texto_claro(aparelho, servidor):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    for modo in ("real", "didatico"):
        conversa = await alice.nova_conversa(["bob"], modo)
        await alice.enviar(conversa.id, f"segredo-{modo}-xyz")
        await esperar(lambda c=conversa: _textos(bob, c.id))
    conteudo = servidor["banco"].read_bytes()
    assert b"segredo-" not in conteudo
    assert b"PRIVATE KEY" not in conteudo


async def test_rastro_do_envio_e_do_recebimento(aparelho):
    alice, bob = await _online(aparelho, "alice"), await _online(aparelho, "bob")
    conversa = await alice.nova_conversa(["bob"], "didatico")
    inicio_a, inicio_b = len(alice.sessao.tracer.eventos), len(bob.sessao.tracer.eventos)
    await alice.enviar(conversa.id, "oi")
    await esperar(lambda: _textos(bob, conversa.id))
    etapas_a = [e.etapa for e in alice.sessao.tracer.eventos[inicio_a:]]
    etapas_b = [e.etapa for e in bob.sessao.tracer.eventos[inicio_b:]]
    assert etapas_a == ["codificacao", "cifragem", "assinatura", "cifragem", "assinatura"]  # bob + cópia
    assert etapas_b == ["verificacao", "decifragem", "decodificacao"]
