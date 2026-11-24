"""Autenticação e canal: limite de tentativas de login, tempo igual para usuário inexistente e TLS."""

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import auth as modulo_auth
from backend.auth import LimiteTentativas
from backend.main import criar_app
from frontend.api_client import ApiCliente
from frontend.mensageiro import Mensageiro
from frontend.sessao import Sessao
from shared.crypto import rsa_didatico
from shared.tls import contexto_cliente, gerar_certificados
from tests.conftest import esperar
from tests.test_api_relay import Usuario


@pytest.fixture
def api():
    with TestClient(criar_app("sqlite://")) as cliente:
        yield cliente


def _login(api, username, senha):
    return api.post("/api/auth/login", json={"username": username, "senha": senha})


# ---------------------------------------------------------------- limite de tentativas


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def test_limite_por_usuario_e_janela_deslizante():
    relogio = Relogio()
    limite = LimiteTentativas(por_usuario=3, por_ip=100, janela_s=60, relogio=relogio)
    for _ in range(3):
        assert limite.espera("alice", "1.1.1.1") == 0
        limite.falhou("alice", "1.1.1.1")
        relogio.agora += 10
    assert limite.espera("alice", "1.1.1.1") == 30  # a 1ª falha sai da janela em 60 − 30 s
    assert limite.espera("alice", "2.2.2.2") == 30  # trocar de IP não ajuda: o limite é também por usuário
    assert limite.espera("bob", "1.1.1.1") == 0
    relogio.agora += 30
    assert limite.espera("alice", "1.1.1.1") == 0


def test_limite_por_ip_pega_quem_varre_varios_usuarios():
    limite = LimiteTentativas(por_usuario=5, por_ip=4, relogio=Relogio())
    for nome in ("a", "b", "c", "d"):
        limite.falhou(nome, "6.6.6.6")
    assert limite.espera("e", "6.6.6.6") > 0
    assert limite.espera("e", "7.7.7.7") == 0


def test_acerto_zera_as_falhas_do_usuario():
    limite = LimiteTentativas(por_usuario=2, relogio=Relogio())
    limite.falhou("alice", "ip")
    limite.acertou("alice")
    limite.falhou("alice", "ip")
    assert limite.espera("alice", "ip") == 0


def test_login_bloqueia_depois_de_cinco_falhas(api):
    Usuario(api, "alice", rsa_didatico.gerar(32))
    for _ in range(5):
        assert _login(api, "alice", "errada").status_code == 401
    bloqueado = _login(api, "alice", "segredo123")  # nem a senha certa entra durante o bloqueio
    assert bloqueado.status_code == 429
    assert int(bloqueado.headers["Retry-After"]) > 0
    assert "muitas tentativas" in bloqueado.json()["detail"]


def test_bloqueio_vale_tambem_para_usuario_inexistente(api):
    """Senão a diferença entre 401 e 429 revelaria quem tem conta."""
    for _ in range(5):
        assert _login(api, "fantasma", "x").status_code == 401
    assert _login(api, "fantasma", "x").status_code == 429


def test_login_certo_zera_o_contador(api):
    Usuario(api, "alice", rsa_didatico.gerar(32))
    for _ in range(4):
        _login(api, "alice", "errada")
    assert _login(api, "alice", "segredo123").status_code == 200
    for _ in range(4):
        assert _login(api, "alice", "errada").status_code == 401


def test_usuario_inexistente_tambem_paga_o_argon2(api, monkeypatch):
    chamadas = []
    original = modulo_auth.verificar_senha
    monkeypatch.setattr(modulo_auth, "verificar_senha", lambda h, s: chamadas.append(h) or original(h, s))
    assert _login(api, "ninguem", "qualquer").status_code == 401
    assert chamadas == [modulo_auth._HASH_FICTICIO]


# ---------------------------------------------------------------- TLS


def test_certificado_do_servidor_e_assinado_pela_ac(tmp_path):
    from cryptography import x509

    arquivos = gerar_certificados(tmp_path)
    ca = x509.load_pem_x509_certificate(arquivos.ca.read_bytes())
    certificado = x509.load_pem_x509_certificate(arquivos.certificado.read_bytes())
    certificado.verify_directly_issued_by(ca)
    nomes = certificado.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in nomes.get_values_for_type(x509.DNSName)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ca.pem", "servidor-chave.pem", "servidor.pem"]  # sem a chave da AC


async def test_mensagem_trafega_por_https_e_wss(servidor_tls, tmp_path):
    contexto = contexto_cliente(servidor_tls["ca"])
    aparelhos = []
    for nome in ("alice", "bob"):
        m = Mensageiro(Sessao(ApiCliente(servidor_tls["http"], tls=contexto), tmp_path / nome), servidor_tls["ws"])
        await m.sessao.cadastrar(nome, nome.title(), "segredo123", bits_didatico=32)
        await m.conectar()
        aparelhos.append(m)
    alice, bob = aparelhos
    try:
        conversa = await alice.nova_conversa(["bob"], "real")
        await esperar(lambda: conversa.id in bob.conversas)
        await alice.enviar(conversa.id, "por um canal cifrado")
        await esperar(lambda: [i.texto for i in bob.conversas[conversa.id].ordenadas()] == ["por um canal cifrado"])
    finally:
        for m in aparelhos:
            await m.desconectar()
            await m.sessao.api.fechar()


async def test_cliente_recusa_servidor_com_certificado_de_outra_ac(servidor_tls, tmp_path):
    """Um intermediário com certificado próprio não engana o cliente: ele só confia na AC do projeto."""
    outra_ac = gerar_certificados(tmp_path / "outra").ca
    api = ApiCliente(servidor_tls["http"], tls=contexto_cliente(outra_ac))
    try:
        with pytest.raises(httpx.ConnectError):
            await api.login("alice", "segredo123")
    finally:
        await api.fechar()


async def test_canal_em_claro_nao_responde(servidor_tls):
    """Com TLS ligado, um cliente http:// não consegue conversar com o servidor."""
    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPError):
            await http.get(servidor_tls["http"].replace("https://", "http://") + "/api/health")
