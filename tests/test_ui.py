"""Telas do NiceGUI com o simulador de usuário: Alice usa a interface, Bob é um aparelho programático."""

from pathlib import Path

from nicegui.testing.user_simulation import user_simulation

from frontend.api_client import ApiCliente
from frontend.mensageiro import Mensageiro
from frontend.sessao import Sessao
from tests.conftest import esperar

MAIN = Path(__file__).resolve().parent.parent / "frontend" / "main.py"


async def test_cadastro_e_conversa_pela_interface(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIPTOCHAT_API", servidor["http"])
    monkeypatch.setenv("CRIPTOCHAT_KEYSTORE", str(tmp_path / "aparelho-alice"))

    bob = Mensageiro(Sessao(ApiCliente(servidor["http"]), tmp_path / "aparelho-bob"), servidor["ws"])
    await bob.sessao.cadastrar("bob", "Bob", "segredo456")
    await bob.conectar()

    try:
        async with user_simulation(main_file=MAIN) as alice:
            await alice.open("/chat")
            await alice.should_see("Entrar")  # sem sessão, vai para o login

            await alice.open("/cadastro")
            alice.find(marker="cadastro-usuario").type("alice")
            alice.find(marker="cadastro-nome").type("Alice")
            alice.find(marker="cadastro-senha").type("segredo123")
            alice.find(marker="cadastro-enviar").click()
            await alice.should_see("Geração da chave didática", retries=100)
            await alice.should_see("φ(n)")

            await alice.open("/chat")
            alice.find(marker="chat-nova").click()
            await alice.should_see("Bob")  # a lista de pessoas mostra o nome e o @usuário
            alice.find(marker="chat-contato-bob").click()
            alice.find(marker="chat-criar").click()
            await alice.should_see("Criptografia ponta a ponta", retries=50)

            alice.find(marker="chat-texto").type("oi do navegador")
            await alice.should_see("15/2000 caracteres")
            alice.find(marker="chat-enviar").click()
            await esperar(lambda: any(
                i.texto == "oi do navegador" and i.status == "verificada"
                for c in bob.conversas.values() for i in c.mensagens.values()
            ))
            await alice.should_see("entregue a todos", retries=50)

            conversa = next(iter(bob.conversas))
            await bob.enviar(conversa, "resposta do bob")
            await alice.should_see("resposta do bob", retries=50)
            await alice.should_see("assinatura de bob verificada", retries=50)

            alice.find("Sair").click()
            await alice.should_see("Entrar", retries=50)
    finally:
        await bob.desconectar()
        await bob.sessao.api.fechar()


async def test_trocar_e_excluir_chave_pela_interface(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIPTOCHAT_API", servidor["http"])
    monkeypatch.setenv("CRIPTOCHAT_KEYSTORE", str(tmp_path / "aparelho-alice"))

    async with user_simulation(main_file=MAIN) as alice:
        await alice.open("/cadastro")
        alice.find(marker="cadastro-usuario").type("alice")
        alice.find(marker="cadastro-nome").type("Alice")
        alice.find(marker="cadastro-senha").type("segredo123")
        alice.find(marker="cadastro-enviar").click()
        await alice.should_see("Geração da chave didática", retries=100)

        await alice.open("/chaves")
        alice.find(marker="trocar-real").click()
        await alice.should_see("substituída · privada neste aparelho", retries=100)

        alice.find(marker="excluir-didatico").click()
        alice.find(marker="excluir-senha").type("segredo123")
        alice.find(marker="excluir-confirmar").click()
        await alice.should_see("revogada · privada neste aparelho", retries=50)
        await alice.should_see("Publicar nova chave", retries=50)
