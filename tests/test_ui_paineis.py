"""Telas novas com o simulador de usuário: Inspetor, Caminho, Observador, Servidores, Clientes, Laboratório e Dashboard."""

from pathlib import Path

from nicegui.testing.user_simulation import user_simulation

from frontend.api_client import ApiCliente
from frontend.mensageiro import Mensageiro
from frontend.sessao import Sessao
from tests.conftest import esperar

MAIN = Path(__file__).resolve().parent.parent / "frontend" / "main.py"


async def _cadastrar_pela_interface(usuario, nome: str) -> None:
    await usuario.open("/cadastro")
    usuario.find(marker="cadastro-usuario").type(nome)
    usuario.find(marker="cadastro-nome").type(nome.title())
    usuario.find(marker="cadastro-senha").type("segredo123")
    usuario.find(marker="cadastro-enviar").click()
    await usuario.should_see("Sua chave pública já está no servidor", retries=100)


async def _no_ligado(mensageiro: Mensageiro, nome: str) -> bool:
    return next(n for n in await mensageiro.sessao.api.servidores() if n.nome == nome).ativo


async def test_paineis_do_administrador(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIPTOCHAT_API", servidor["http"])
    monkeypatch.setenv("CRIPTOCHAT_KEYSTORE", str(tmp_path / "aparelho-alice"))
    bob = Mensageiro(Sessao(ApiCliente(servidor["http"]), tmp_path / "aparelho-bob"), servidor["ws"])
    try:
        async with user_simulation(main_file=MAIN) as alice:
            await _cadastrar_pela_interface(alice, "alice")  # primeiro cadastro: administradora
            await bob.sessao.cadastrar("bob", "Bob", "segredo456")
            await bob.conectar()
            conversa = await bob.nova_conversa(["alice"], "real")

            await alice.open("/chat")
            await alice.should_see("Criptografia ponta a ponta", retries=50)
            alice.find(marker="chat-texto").type("raio-x")
            alice.find(marker="chat-enviar").click()
            await esperar(lambda: [i.texto for i in bob.conversas[conversa.id].mensagens.values()] == ["raio-x"])

            # Inspetor: os passos, rede e experimentos
            await alice.open("/inspetor")
            await alice.should_see("Cifrar com a chave pública de @bob", retries=50)
            await alice.should_see("bloco(s) RSA-OAEP")
            await alice.should_see("Manaus › Brasília › São Paulo")  # passo "rede", do rastro do servidor
            alice.find(marker="experimento-adulterar").click()
            await alice.should_see("a assinatura deixa de conferir", retries=20)
            alice.find(marker="experimento-chave-errada").click()
            await alice.should_see("com a chave errada ele recusa", retries=100)

            # Caminho da mensagem: o percurso pelos nós, até a confirmação de Bob
            await alice.open("/caminho")
            await alice.should_see("Etapas do percurso", retries=50)
            await alice.should_see("Brasília")
            await alice.should_see("recebeu e confirmou", retries=50)

            # Observador: visão do servidor e do interceptador, que não consegue ler o RSA de 2048 bits
            await alice.open("/observador")
            await alice.should_see("Visão do servidor", retries=50)
            await alice.should_see("Visão do interceptador")
            await alice.should_see("inviável")

            # Servidores: o interruptor desliga o nó do meio do caminho
            await alice.open("/servidores")
            await alice.should_see("Topologia", retries=50)
            alice.find(marker="servidor-ligado-Brasília").click()
            await alice.should_see("Nó Brasília desligado: caminhos recalculados", retries=50)
            assert not await _no_ligado(bob, "Brasília")

            # Clientes: editar o próprio nome
            await alice.open("/clientes")
            await alice.should_see("@bob", retries=50)
            alice.find(marker="cliente-editar-alice").click()
            alice.find(marker="cliente-nome").clear().type("Alice Admin")
            alice.find(marker="cliente-salvar").click()
            await alice.should_see("Alice Admin", retries=50)

            # Laboratório: o exemplo clássico e a chave didática de Bob pelo diretório
            await alice.open("/laboratorio")
            alice.find(marker="lab-n").type("3233")
            alice.find(marker="lab-quebrar-n").click()
            await alice.should_see("3233 = 53 × 61", retries=50)
            alice.find(marker="lab-usuario").type("bob")
            alice.find(marker="lab-quebrar").click()
            await alice.should_see("chave didática de @bob", retries=100)
            await alice.should_see("a chave privada foi recuperada")

            await alice.open("/")
            await alice.should_see("Roteiro da demonstração", retries=50)
            await alice.should_see("Nós ligados")
            await alice.should_see("Caminho da mensagem")  # no menu lateral
            await alice.should_not_see("Laboratório")  # fora do menu e do roteiro
    finally:
        await bob.desconectar()
        await bob.sessao.api.fechar()


async def test_paineis_de_um_usuario_comum(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIPTOCHAT_API", servidor["http"])
    monkeypatch.setenv("CRIPTOCHAT_KEYSTORE", str(tmp_path / "aparelho-bob"))
    alice = Mensageiro(Sessao(ApiCliente(servidor["http"]), tmp_path / "aparelho-alice"), servidor["ws"])
    await alice.sessao.cadastrar("alice", "Alice", "segredo456")  # a administradora é ela
    try:
        async with user_simulation(main_file=MAIN) as bob:
            await _cadastrar_pela_interface(bob, "bob")

            await bob.open("/observador")
            await bob.should_see("Só administradores acompanham o tráfego", retries=50)
            await bob.should_not_see(marker="observador-adulterar")

            await bob.open("/servidores")
            await bob.should_see("Topologia", retries=50)
            await bob.should_not_see(marker="servidor-novo")

            # Minhas chaves: apagar a privada deste aparelho (simulação "apagar privada")
            await bob.open("/chaves")
            await bob.should_see("Onde cada chave fica", retries=50)
            mesmo_aparelho = Sessao(ApiCliente(servidor["http"]), tmp_path / "aparelho-bob")
            await mesmo_aparelho.entrar("bob", "segredo123")
            key_id = mesmo_aparelho.keystore.ativa("real").publica.key_id
            await mesmo_aparelho.api.fechar()
            bob.find(marker=f"apagar-{key_id}").click()
            bob.find(marker="apagar-confirmar").click()
            await bob.should_see("ativa · privada ausente", retries=50)

            await bob.open("/login")  # contas com chaves neste aparelho aparecem como atalho
            await bob.should_see("Contas com chaves neste aparelho", retries=50)
    finally:
        await alice.sessao.api.fechar()
