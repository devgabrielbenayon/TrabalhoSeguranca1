"""Quebrar chaves pequenas (RF18): fatorar n e recuperar d só com a chave pública."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shared.crypto import rsa_didatico
from shared.crypto.envelope import decifrar_capturado, montar_envelopes
from shared.crypto.fatoracao import FatoracaoFalhou, fatorar, quebrar
from shared.crypto.rsa_didatico import PublicaDidatica


def test_exemplo_classico():
    fatoracao = fatorar(3233)
    assert (fatoracao.p, fatoracao.q) == (53, 61)
    quebrada = quebrar(PublicaDidatica(17, 3233))
    assert (quebrada.phi, quebrada.d) == (3120, 2753)


@settings(max_examples=15, deadline=None)
@given(st.sampled_from([16, 24, 32, 48, 64]))
def test_fatora_qualquer_chave_didatica(bits):
    geracao = rsa_didatico.gerar_parametros(bits)
    fatoracao = fatorar(geracao.n)
    assert (fatoracao.p, fatoracao.q) == tuple(sorted((geracao.p, geracao.q)))
    assert quebrar(geracao.privada().publica).d == geracao.d


def test_com_a_chave_quebrada_o_atacante_le_a_mensagem():
    alice, bob = rsa_didatico.gerar(32), rsa_didatico.gerar(48)
    para_bob = next(
        e for e in montar_envelopes("pague 10", "alice", alice, {"bob": bob.publica}, 1) if e.to == "bob"
    )
    conteudo = decifrar_capturado(para_bob, quebrar(bob.publica).privada())
    assert conteudo["text"] == "pague 10" and conteudo["from"] == "alice"


@pytest.mark.parametrize("n", [1, 3])
def test_n_pequeno_demais(n):
    with pytest.raises(ValueError):
        fatorar(n)


def test_primo_nao_e_modulo_rsa():
    with pytest.raises(FatoracaoFalhou):
        fatorar(rsa_didatico.gerar_primo(40))


def test_desiste_no_limite_de_passos():
    n = rsa_didatico.gerar_parametros(64).n
    with pytest.raises(FatoracaoFalhou):
        fatorar(n, limite_passos=10)
