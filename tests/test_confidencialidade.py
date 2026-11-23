"""Tela Confidencialidade: o par gerado número por número e os códigos que batem nos dois aparelhos."""

import pytest

from frontend import confidencialidade as conf
from frontend.pages.layout import cores_do_codigo
from shared.crypto import rsa_real
from shared.crypto.envelope import abrir_envelope, montar_envelopes
from shared.crypto.rsa_didatico import PublicaDidatica, eh_primo
from shared.crypto.rsa_real import PublicaReal
from shared.schemas import Envelope


@pytest.mark.parametrize("bits", [32, 2048])
def test_par_gerado_numero_por_numero(bits):
    g = conf.gerar(bits)
    assert eh_primo(g.p.valor) and eh_primo(g.q.valor) and g.p.valor != g.q.valor
    assert g.p.candidatos >= 1 and g.q.candidatos >= 1
    assert g.n == g.p.valor * g.q.valor and g.n.bit_length() == bits
    assert g.phi == (g.p.valor - 1) * (g.q.valor - 1)
    assert g.e == 65537 and g.e * g.d % g.phi == 1
    m, c, volta = g.teste
    assert volta == m != c
    assert isinstance(g.publica, PublicaReal if bits == 2048 else PublicaDidatica)
    assert g.publica.numeros == {"e": g.e, "n": g.n}


def test_numero_da_dupla_e_igual_nos_dois_aparelhos():
    alice, bob, carol = (rsa_real.gerar().publica.fingerprint for _ in range(3))
    assert conf.numero_conversa(alice, bob) == conf.numero_conversa(bob, alice)
    assert conf.numero_conversa(alice, bob) != conf.numero_conversa(alice, carol)
    assert len(conf.numero_conversa(alice, bob).split()) == 12


def test_codigos_batem_entre_quem_envia_e_quem_recebe():
    alice, bob = rsa_real.gerar(), rsa_real.gerar()
    enviado = next(e for e in montar_envelopes("segredo", "alice", alice, {"bob": bob.publica}, 1) if e.to == "bob")
    recebido = Envelope.model_validate(enviado.para_json())  # o que atravessou a rede

    assert conf.resumo_cifrado(recebido) == conf.resumo_cifrado(enviado)
    texto = abrir_envelope(recebido, bob, alice.publica).texto
    assert conf.resumo_texto(texto) == conf.resumo_texto("segredo")
    assert len(conf.bytes_cifrados(enviado)) == 256  # um bloco RSA-OAEP de 2048 bits
    assert b"segredo" not in conf.bytes_cifrados(enviado)


def test_faixa_de_cores_e_deterministica():
    codigo = conf.resumo(b"x")
    assert cores_do_codigo(codigo) == cores_do_codigo(codigo)
    assert len(cores_do_codigo(codigo)) == 8
    assert cores_do_codigo(codigo) != cores_do_codigo(conf.resumo(b"y"))
