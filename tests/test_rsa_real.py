import pytest

from shared.crypto import rsa_real
from shared.crypto.chaves import carregar_publica


@pytest.fixture(scope="module")
def privada():
    return rsa_real.gerar()


@pytest.fixture(scope="module")
def outra():
    return rsa_real.gerar()


def test_tamanho_do_bloco_oaep(privada):
    assert privada.publica.tamanho_bloco == 190


@pytest.mark.parametrize("tamanho", [0, 1, 189, 190])
def test_bloco_ida_e_volta(privada, tamanho):
    bloco = bytes(range(tamanho))
    assert privada.decifrar_bloco(privada.publica.cifrar_bloco(bloco)) == bloco


def test_bloco_191_bytes_e_recusado(privada):
    with pytest.raises(ValueError):
        privada.publica.cifrar_bloco(b"x" * 191)


def test_oaep_e_aleatorio(privada):
    assert privada.publica.cifrar_bloco(b"A") != privada.publica.cifrar_bloco(b"A")


def test_chave_errada_e_rejeitada(privada, outra):
    with pytest.raises(ValueError):
        outra.decifrar_bloco(privada.publica.cifrar_bloco(b"segredo"))


def test_assinatura_pss(privada, outra):
    assinatura = privada.assinar(b"mensagem")
    assert privada.publica.verificar(b"mensagem", assinatura)
    assert not privada.publica.verificar(b"mensagen", assinatura)
    assert not outra.publica.verificar(b"mensagem", assinatura)


def test_exportar_publica(privada):
    copia = carregar_publica(privada.publica.exportar())
    assert copia.key_id == privada.publica.key_id
    assert copia.numeros["e"] == 65537 and copia.numeros["n"].bit_length() == 2048


def test_keystore_pem_com_senha(privada):
    pem = privada.exportar("senha-forte")
    assert b"ENCRYPTED" in pem
    assert rsa_real.PrivadaReal.carregar(pem, "senha-forte").publica.key_id == privada.publica.key_id
    with pytest.raises(ValueError):
        rsa_real.PrivadaReal.carregar(pem, "senha-errada")


def test_identidade_da_chave(privada):
    pub = privada.publica
    assert pub.key_id.startswith("k_") and len(pub.key_id) == 18
    assert len(pub.fingerprint_formatado.split(":")) == 16
    blocos = pub.numero_seguranca.split()
    assert len(blocos) == 12 and all(len(b) == 5 and b.isdigit() for b in blocos)
