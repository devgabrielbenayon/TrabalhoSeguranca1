import pytest

from frontend.keystore import ChaveNaoEncontrada, Keystore
from shared.crypto import rsa_didatico, rsa_real


@pytest.fixture(scope="module")
def real():
    return rsa_real.gerar()


def test_guardar_e_carregar_dos_dois_modos(tmp_path, real):
    didatica = rsa_didatico.gerar(32)
    ks = Keystore(tmp_path, "alice", "segredo123")
    assert not ks.existe()
    ks.guardar(real)
    ks.guardar(didatica)

    novo = Keystore(tmp_path, "alice", "segredo123")  # outro processo, nada em memória
    assert novo.existe()
    assert novo.ativa("real").publica.key_id == real.publica.key_id
    assert novo.ativa("didatico").d == didatica.d


def test_pem_fica_cifrado_com_a_senha(tmp_path, real):
    ks = Keystore(tmp_path, "alice", "segredo123")
    ks.guardar(real)
    assert b"ENCRYPTED PRIVATE KEY" in (ks.pasta / f"{real.publica.key_id}.pem").read_bytes()
    with pytest.raises(ValueError):
        Keystore(tmp_path, "alice", "senha-errada").ativa("real")


def test_troca_mantem_a_antiga(tmp_path):
    antiga, nova = rsa_didatico.gerar(32), rsa_didatico.gerar(32)
    ks = Keystore(tmp_path, "alice", "x" * 6)
    ks.guardar(antiga)
    ks.guardar(nova)
    assert ks.ativa("didatico").publica.key_id == nova.publica.key_id
    assert Keystore(tmp_path, "alice", "x" * 6).carregar(antiga.publica.key_id).d == antiga.d
    assert [c["ativa"] for c in ks.listar()] == [False, True]


def test_apagar(tmp_path):
    chave = rsa_didatico.gerar(32)
    ks = Keystore(tmp_path, "alice", "x" * 6)
    ks.guardar(chave)
    ks.apagar(chave.publica.key_id)
    assert ks.ativa("didatico") is None
    with pytest.raises(ChaveNaoEncontrada):
        Keystore(tmp_path, "alice", "x" * 6).carregar(chave.publica.key_id)
    with pytest.raises(ChaveNaoEncontrada):
        ks.apagar(chave.publica.key_id)
