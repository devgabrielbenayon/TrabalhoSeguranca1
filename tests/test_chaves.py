import pytest

from shared.crypto.chaves import carregar_publica, gerar_par


@pytest.mark.parametrize("modo, bits", [("didatico", None), ("didatico", 16), ("real", None)])
def test_gerar_e_recarregar_publica(modo, bits):
    privada = gerar_par(modo, bits)
    copia = carregar_publica(privada.publica.exportar())
    assert copia.modo == modo
    assert copia.key_id == privada.publica.key_id
    assert copia.numeros == privada.publica.numeros


def test_modo_desconhecido():
    with pytest.raises(ValueError):
        gerar_par("aes")


def test_publica_desconhecida():
    with pytest.raises(ValueError):
        carregar_publica('{"modo": "outro", "e": 3, "n": 33}')
