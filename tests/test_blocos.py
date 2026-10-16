import pytest
from hypothesis import given
from hypothesis import strategies as st

from shared.crypto.blocos import (
    MAX_TEXTO_BYTES,
    MensagemGrandeDemais,
    codificar_conteudo,
    decodificar_conteudo,
    dividir,
    juntar,
)


@pytest.mark.parametrize("tamanho, esperado", [(189, [190, 190, 189]), (190, [190, 190, 190]), (191, [190, 190, 190, 1])])
def test_limites_do_bloco_real(tamanho, esperado):
    dados = b"x" * (tamanho + 380)
    assert [len(b) for b in dividir(dados, 190)] == esperado


def test_completar_e_remover_preenchimento():
    blocos = dividir(b'{"a":1}', 3, completar=True)
    assert [len(b) for b in blocos] == [3, 3, 3]
    assert juntar(blocos, remover_preenchimento=True) == b'{"a":1}'


def test_acentos_viram_mais_de_um_byte():
    conteudo = codificar_conteudo("alice", "m1", "ação")
    assert decodificar_conteudo(conteudo)["text"] == "ação"
    assert b"\xc3\xa7" in conteudo  # "ç" em UTF-8


def test_limite_de_tamanho():
    codificar_conteudo("a", "m", "x" * MAX_TEXTO_BYTES)
    with pytest.raises(MensagemGrandeDemais):
        codificar_conteudo("a", "m", "x" * (MAX_TEXTO_BYTES + 1))
    with pytest.raises(MensagemGrandeDemais):
        codificar_conteudo("a", "m", "ç" * (MAX_TEXTO_BYTES // 2 + 1))  # conta bytes, não caracteres


def test_conteudo_sem_cabecalho():
    with pytest.raises(ValueError):
        decodificar_conteudo(b'{"text":"oi"}')


@given(texto=st.text(max_size=300), tamanho=st.integers(min_value=1, max_value=200))
def test_dividir_e_juntar(texto, tamanho):
    conteudo = codificar_conteudo("alice", "m1", texto)
    assert juntar(dividir(conteudo, tamanho, completar=True), remover_preenchimento=True) == conteudo
    assert juntar(dividir(conteudo, tamanho)) == conteudo
