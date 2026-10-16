from math import gcd

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shared.crypto import rsa_didatico as rd


def test_exemplo_classico_do_plano():
    g = rd.gerar_parametros(p=61, q=53, e=17)
    assert (g.n, g.phi, g.e, g.d) == (3233, 3120, 17, 2753)
    privada = g.privada()
    passos: list[dict] = []
    c = privada.publica.cifrar_int(65, passos)
    assert c == 2790
    assert len(passos) == (17).bit_length()
    assert privada.decifrar_int(c) == 65


def test_tabela_square_and_multiply():
    passos: list[dict] = []
    rd.pow_mod_trace(65, 17, 3233, passos)
    assert [p["bit"] for p in passos] == list(bin(17)[2:])
    assert all(("multiplica" in p) == (p["bit"] == "1") for p in passos)
    assert passos[-1]["multiplica"] == 2790


@pytest.mark.parametrize("a, b", [(17, 3120), (240, 46), (1, 1), (65537, 2**32)])
def test_egcd(a, b):
    g, x, y = rd.egcd(a, b)
    assert g == gcd(a, b) and a * x + b * y == g


def test_inverso_modular_sem_inverso():
    with pytest.raises(ValueError):
        rd.inverso_modular(6, 3120)


@pytest.mark.parametrize("n", [2, 3, 5, 61, 53, 7919, 2**31 - 1, 2**61 - 1])
def test_primos(n):
    assert rd.eh_primo(n)


@pytest.mark.parametrize("n", [0, 1, 4, 3233, 561, 1105, 1729, 2**32 + 1])  # inclui números de Carmichael
def test_compostos(n):
    assert not rd.eh_primo(n)


def test_pow_mod_rejeita_base_fora_do_intervalo():
    with pytest.raises(ValueError):
        rd.pow_mod_trace(3233, 17, 3233)


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        rd.gerar_parametros(p=61, q=61)
    with pytest.raises(ValueError):
        rd.gerar_parametros(p=61, q=55)
    with pytest.raises(ValueError):
        rd.gerar_parametros(p=61, q=53, e=3)  # 3 divide φ = 3120
    with pytest.raises(ValueError):
        rd.gerar_parametros(bits=8)


@settings(max_examples=40, deadline=None)
@given(bits=st.integers(min_value=rd.BITS_MIN, max_value=rd.BITS_MAX))
def test_geracao_aleatoria(bits):
    g = rd.gerar_parametros(bits)
    assert g.n.bit_length() == bits
    assert g.p != g.q and g.n == g.p * g.q
    assert gcd(g.e, g.phi) == 1 and (g.e * g.d) % g.phi == 1


@settings(max_examples=60, deadline=None)
@given(bits=st.integers(min_value=rd.BITS_MIN, max_value=rd.BITS_MAX), dados=st.binary(min_size=0, max_size=7))
def test_bloco_ida_e_volta(bits, dados):
    privada = rd.gerar(bits)
    bloco = dados[: privada.publica.tamanho_bloco].rjust(privada.publica.tamanho_bloco, b"\x00")
    assert privada.decifrar_bloco(privada.publica.cifrar_bloco(bloco)) == bloco


def test_bloco_grande_demais():
    publica = rd.gerar_parametros(p=61, q=53, e=17).privada().publica
    assert publica.tamanho_bloco == 1
    with pytest.raises(ValueError):
        publica.cifrar_bloco(b"ab")


def test_rsa_de_livro_e_deterministico():
    """A mesma letra vira sempre o mesmo número: o padrão que o Inspetor destaca."""
    publica = rd.gerar_parametros(p=61, q=53, e=17).privada().publica
    assert publica.cifrar_bloco(b"A") == publica.cifrar_bloco(b"A")


@settings(max_examples=30, deadline=None)
@given(dados=st.binary(max_size=200))
def test_assinatura(dados):
    privada = rd.gerar(64)
    assinatura = privada.assinar(dados)
    assert privada.publica.verificar(dados, assinatura)


def test_assinatura_adulterada():
    privada = rd.gerar(64)
    assinatura = privada.assinar(b"ola")
    assert not privada.publica.verificar(b"olb", assinatura)
    adulterada = (int.from_bytes(assinatura, "big") ^ 1).to_bytes(len(assinatura), "big")
    assert not privada.publica.verificar(b"ola", adulterada)


def test_exportar_e_carregar_privada():
    privada = rd.gerar(32)
    copia = rd.PrivadaDidatica.carregar(privada.exportar())
    assert copia.d == privada.d and copia.publica.key_id == privada.publica.key_id
