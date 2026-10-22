"""Dados do Inspetor (RF14) e medições do Laboratório (RF18), sem interface."""

import base64
import math
from datetime import datetime, timezone

import pytest

from frontend import inspecao, medicoes
from frontend.inspecao import Percurso
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.envelope import montar_envelopes
from shared.schemas import EventoTransitoOut
from shared.trace import Tracer


@pytest.fixture(scope="module")
def reais():
    return rsa_real.gerar(), rsa_real.gerar()


def _para(remetente, destinatario, texto="olá, inspetor", tracer=None):
    envelopes = montar_envelopes(texto, "alice", remetente, {"bob": destinatario.publica}, 1, tracer=tracer or Tracer("t", ativo=False))
    return next(e for e in envelopes if e.to == "bob")


def test_rastro_do_envio_tem_os_numeros_do_modo_didatico():
    alice, bob = rsa_didatico.gerar(32), rsa_didatico.gerar(32)
    tracer = Tracer("alice")
    envelope = _para(alice, bob, tracer=tracer)
    eventos = inspecao.eventos_da_mensagem(tracer, envelope.message_id)
    cifragem = next(e for e in eventos if e.etapa == "cifragem" and e.entrada["para"] == "bob")
    assert (cifragem.detalhes["e"], cifragem.detalhes["n"]) == (bob.publica.e, bob.n)
    bloco = cifragem.detalhes["blocos"][0]
    assert pow(bloco["m"], bob.publica.e, bob.n) == bloco["c"]  # c = mᵉ mod n confere à mão
    assinatura = next(e for e in eventos if e.etapa == "assinatura" and e.entrada["para"] == "bob")
    assert assinatura.detalhes["d"] == alice.d
    assert pow(assinatura.detalhes["h"], alice.d, alice.n) == int.from_bytes(base64.b64decode(assinatura.saida), "big")


def test_refazer_o_recebimento_de_uma_mensagem_do_historico():
    alice, bob = rsa_didatico.gerar(32), rsa_didatico.gerar(32)
    eventos = inspecao.refazer_recebimento(_para(alice, bob), bob, alice.publica)
    assert [e.etapa for e in eventos] == ["verificacao", "decifragem", "decodificacao"]
    verificacao, decifragem, texto = eventos
    assert verificacao.saida is True and pow(verificacao.detalhes["s"], alice.publica.e, alice.n) == verificacao.detalhes["h"]
    assert decifragem.detalhes["d"] == bob.d and texto.saida == "olá, inspetor"


def test_refazer_com_assinatura_errada_registra_o_erro():
    alice, bob, mallory = rsa_didatico.gerar(32), rsa_didatico.gerar(32), rsa_didatico.gerar(32)
    envelope = _para(alice, bob)
    envelope.from_key_id = mallory.publica.key_id
    eventos = inspecao.refazer_recebimento(envelope, bob, mallory.publica)
    assert [e.etapa for e in eventos] == ["verificacao"] and "AssinaturaInvalida" in eventos[0].detalhes["erro"]


def test_chave_errada_no_modo_didatico_da_lixo_sem_aviso():
    alice, bob = rsa_didatico.gerar(32), rsa_didatico.gerar(32)
    experimento = inspecao.decifrar_com_outra_chave(_para(alice, bob), rsa_didatico.gerar(32))
    assert experimento.texto_obtido is not None and "olá, inspetor" not in experimento.texto_obtido
    assert len(experimento.linhas) == len(_para(alice, bob).blocks) and "lixo" in experimento.conclusao


def test_chave_errada_no_modo_real_o_oaep_recusa(reais):
    alice, bob = reais
    experimento = inspecao.decifrar_com_outra_chave(_para(alice, bob), rsa_real.gerar())
    assert experimento.texto_obtido is None and experimento.erros
    assert all("decifrou" not in e for e in experimento.erros) and "OAEP" in experimento.conclusao


@pytest.mark.parametrize("modo", ["didatico", "real"])
def test_um_bit_trocado_invalida_a_assinatura(modo, reais):
    alice, bob = reais if modo == "real" else (rsa_didatico.gerar(32), rsa_didatico.gerar(32))
    experimento = inspecao.adulterar_e_verificar(_para(alice, bob), alice.publica)
    assert [linha["confere"] for linha in experimento.linhas] == [True, False]
    assert experimento.linhas[0]["sha256"] != experimento.linhas[1]["sha256"]


def _transito(etapa, ator, entrada, saida=None):
    return EventoTransitoOut(etapa=etapa, ator=ator, entrada=entrada, saida=saida, duracao_ms=0, ts=datetime.now(timezone.utc))


def test_percurso_vale_a_ultima_tentativa():
    rede = [
        _transito("recebido", "Manaus", {"de": "alice", "para": ["alice", "bob"]}),
        _transito("salto", "Manaus", {"de": "@alice", "para": "bob"}, {"repassa_para": "São Paulo"}),
        _transito("salto", "São Paulo", {"de": "Manaus", "para": "bob"}, {"repassa_para": "@bob"}),
        _transito("fila", "São Paulo", {"para": "bob"}, {"motivo": "offline"}),
    ]
    assert inspecao.percurso(rede, "bob") == Percurso("bob", ["Manaus", "São Paulo"], "offline", "São Paulo")
    # a reentrega da fila do nó do destinatário não registra os saltos de novo: o caminho continua valendo
    rede += [
        _transito("entregue", "São Paulo", {"para": "bob"}, "repassado pelo WebSocket"),
        _transito("confirmado", "São Paulo", {"por": "bob"}, "entrega confirmada"),
    ]
    assert inspecao.percurso(rede, "bob") == Percurso("bob", ["Manaus", "São Paulo"], "entregue", None, confirmado=True)
    assert inspecao.percurso(rede, "carol").status == "a_caminho"


def test_sem_caminho_o_diagrama_recebe_none():
    rede = [_transito("fila", "Manaus", {"para": "bob"}, {"motivo": "sem_rota"})]
    percurso = inspecao.percurso(rede, "bob")
    assert (percurso.status, percurso.caminho, percurso.parado_em) == ("sem_rota", None, "Manaus")


def test_medir_uma_chave_pequena():
    medicao = medicoes.medir_chave(64)
    assert medicao.bits == 64 and medicao.biblioteca_geracao_ms is None
    assert medicao.geracao_ms > 0 and medicao.decifrar_ms >= 0
    assert medicoes.medir_fatoracao(24, repeticoes=1) >= 0


def test_extrapolacao_dobra_a_cada_4_bits():
    assert medicoes.log10_tempo_fatoracao(64, 10.0, 68) == pytest.approx(math.log10(20.0))
    assert medicoes.formatar_log10_ms(math.log10(250)) == "250.0 ms"
    assert medicoes.formatar_log10_ms(math.log10(5_000)) == "5.0 s"
    assert medicoes.formatar_log10_ms(medicoes.log10_tempo_fatoracao(64, 20.0, 2048)).startswith("≈ 10^")
