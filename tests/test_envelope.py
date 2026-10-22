"""Fluxos 5.2 (A → B) e 5.3 (A → B e C) no nível da criptografia, nos dois modos."""

import base64

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.blocos import MAX_TEXTO_CARACTERES, MensagemGrandeDemais
from shared.crypto.envelope import (
    AssinaturaInvalida,
    CabecalhoInconsistente,
    ChaveIncompativel,
    ConteudoIlegivel,
    abrir_envelope,
    montar_envelopes,
)
from shared.trace import Tracer

GERADORES = {"didatico": lambda: rsa_didatico.gerar(32), "real": rsa_real.gerar}


@pytest.fixture(scope="module", params=["didatico", "real"])
def usuarios(request):
    gerar = GERADORES[request.param]
    return {nome: gerar() for nome in ("alice", "bob", "carol", "mallory")}


def _por_destinatario(envelopes):
    return {env.to: env for env in envelopes}


def test_a_para_b_com_copia(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    envs = _por_destinatario(montar_envelopes("Olá, Bob! ção", "alice", alice, {"bob": bob.publica}, 1))
    assert set(envs) == {"bob", "alice"}
    assert abrir_envelope(envs["bob"], bob, alice.publica).texto == "Olá, Bob! ção"
    assert abrir_envelope(envs["alice"], alice, alice.publica).texto == "Olá, Bob! ção"


def test_a_para_b_e_c(usuarios):
    alice, bob, carol = usuarios["alice"], usuarios["bob"], usuarios["carol"]
    envs = _por_destinatario(
        montar_envelopes("oi grupo", "alice", alice, {"bob": bob.publica, "carol": carol.publica}, 7)
    )
    assert set(envs) == {"alice", "bob", "carol"}
    assert len({e.message_id for e in envs.values()}) == 1
    assert abrir_envelope(envs["bob"], bob, alice.publica).texto == "oi grupo"
    assert abrir_envelope(envs["carol"], carol, alice.publica).texto == "oi grupo"
    # B não abre o envelope de C
    with pytest.raises(ChaveIncompativel):
        abrir_envelope(envs["carol"], bob, alice.publica)


def test_sem_copia(usuarios):
    envs = montar_envelopes("x", "alice", usuarios["alice"], {"bob": usuarios["bob"].publica}, 1, incluir_copia=False)
    assert [e.to for e in envs] == ["bob"]


def test_bloco_adulterado_invalida_assinatura(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    env = _por_destinatario(montar_envelopes("pague 10", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    bruto = bytearray(base64.b64decode(env.blocks[0]))
    bruto[-1] ^= 1
    env.blocks[0] = base64.b64encode(bytes(bruto)).decode()
    with pytest.raises(AssinaturaInvalida):
        abrir_envelope(env, bob, alice.publica)


def test_blocos_reordenados_invalidam_assinatura(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    env = _por_destinatario(montar_envelopes("x" * 600, "alice", alice, {"bob": bob.publica}, 1))["bob"]
    assert len(env.blocks) > 1
    env.blocks.reverse()
    with pytest.raises(AssinaturaInvalida):
        abrir_envelope(env, bob, alice.publica)


def test_metadado_alterado_invalida_assinatura(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    env = _por_destinatario(montar_envelopes("oi", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    env.conversation_id = 2
    with pytest.raises(AssinaturaInvalida):
        abrir_envelope(env, bob, alice.publica)


def test_reassinatura_por_terceiro_e_detectada(usuarios):
    """Mallory pega o envelope de A, troca o remetente e assina com a própria chave."""
    alice, bob, mallory = usuarios["alice"], usuarios["bob"], usuarios["mallory"]
    env = _por_destinatario(montar_envelopes("segredo de A", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    env.from_ = "mallory"
    env.from_key_id = mallory.publica.key_id
    env.signature = base64.b64encode(mallory.assinar(env.dados_assinados())).decode()
    with pytest.raises(CabecalhoInconsistente):
        abrir_envelope(env, bob, mallory.publica)


def test_chave_do_remetente_desatualizada(usuarios):
    alice, bob, carol = usuarios["alice"], usuarios["bob"], usuarios["carol"]
    env = _por_destinatario(montar_envelopes("oi", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    with pytest.raises(ChaveIncompativel):
        abrir_envelope(env, bob, carol.publica)


def test_modos_misturados_sao_recusados():
    with pytest.raises(ChaveIncompativel):
        montar_envelopes("oi", "alice", rsa_didatico.gerar(32), {"bob": rsa_real.gerar().publica}, 1)


def test_mensagem_grande_demais(usuarios):
    with pytest.raises(MensagemGrandeDemais):
        montar_envelopes("x" * (MAX_TEXTO_CARACTERES + 1), "alice", usuarios["alice"], {"bob": usuarios["bob"].publica}, 1)


def test_rastreio_registra_as_etapas(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    rastro_a, rastro_b = Tracer("alice"), Tracer("bob")
    env = _por_destinatario(
        montar_envelopes("oi", "alice", alice, {"bob": bob.publica}, 1, incluir_copia=False, tracer=rastro_a)
    )["bob"]
    abrir_envelope(env, bob, alice.publica, tracer=rastro_b)
    assert [e.etapa for e in rastro_a.eventos] == ["codificacao", "cifragem", "assinatura"]
    assert [e.etapa for e in rastro_b.eventos] == ["verificacao", "decifragem", "decodificacao"]
    assert rastro_b.eventos[-1].saida == "oi"
    if env.mode == "didatico":
        assert rastro_a.eventos[1].detalhes["blocos"][0]["passos"]


def test_rastreio_registra_erro(usuarios):
    alice, bob = usuarios["alice"], usuarios["bob"]
    env = _por_destinatario(montar_envelopes("oi", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    env.conversation_id = 99
    rastro = Tracer("bob")
    with pytest.raises(AssinaturaInvalida):
        abrir_envelope(env, bob, alice.publica, tracer=rastro)
    assert "erro" in rastro.eventos[-1].detalhes


def test_chave_errada_no_didatico_vira_lixo():
    alice = rsa_didatico.gerar(32)
    bob = rsa_didatico.gerar(32)
    intruso = rsa_didatico.PrivadaDidatica(rsa_didatico.gerar(32).d, bob.publica)  # d de outro cliente
    env = _por_destinatario(montar_envelopes("segredo", "alice", alice, {"bob": bob.publica}, 1))["bob"]
    with pytest.raises(ConteudoIlegivel):
        abrir_envelope(env, intruso, alice.publica)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(texto=st.text(max_size=400))
def test_propriedade_ida_e_volta(usuarios, texto):
    alice, bob = usuarios["alice"], usuarios["bob"]
    envs = _por_destinatario(montar_envelopes(texto, "alice", alice, {"bob": bob.publica}, 3))
    assert abrir_envelope(envs["bob"], bob, alice.publica).texto == texto
    assert abrir_envelope(envs["alice"], alice, alice.publica).texto == texto
