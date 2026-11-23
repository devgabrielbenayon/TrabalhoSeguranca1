"""Tela Confidencialidade com o simulador de usuário: as três provas que a professora pediu."""

from pathlib import Path

from nicegui.testing.user_simulation import user_simulation

from frontend import confidencialidade as conf
from frontend.api_client import ApiCliente
from frontend.mensageiro import Mensageiro
from frontend.sessao import Sessao
from tests.conftest import esperar

MAIN = Path(__file__).resolve().parent.parent / "frontend" / "main.py"


def _agrupado(codigo: str) -> str:
    return " ".join(codigo[i:i + 4] for i in range(0, 16, 4))


async def test_tres_provas_de_confidencialidade(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIPTOCHAT_API", servidor["http"])
    monkeypatch.setenv("CRIPTOCHAT_KEYSTORE", str(tmp_path / "aparelho-alice"))
    monkeypatch.setattr("frontend.pages.confidencialidade.INTERVALO_QUADRO", 0)
    monkeypatch.setattr("frontend.pages.confidencialidade.PAUSA_PASSO", 0)
    bob = Mensageiro(Sessao(ApiCliente(servidor["http"]), tmp_path / "aparelho-bob"), servidor["ws"])
    try:
        async with user_simulation(main_file=MAIN) as alice:
            await alice.open("/cadastro")
            alice.find(marker="cadastro-usuario").type("alice")
            alice.find(marker="cadastro-nome").type("Alice")
            alice.find(marker="cadastro-senha").type("segredo123")
            alice.find(marker="cadastro-enviar").click()
            await alice.should_see("Sua chave pública já está no servidor", retries=100)

            await bob.sessao.cadastrar("bob", "Bob", "segredo456")
            await bob.conectar()
            conversa = await bob.nova_conversa(["alice"], "real")

            await alice.open("/chat")
            await alice.should_see("Criptografia ponta a ponta", retries=50)
            alice.find(marker="chat-texto").type("so nos dois")
            alice.find(marker="chat-enviar").click()
            await esperar(lambda: [i.texto for i in bob.conversas[conversa.id].mensagens.values()] == ["so nos dois"])
            recebido = next(iter(bob.conversas[conversa.id].mensagens.values())).envelopes[0]

            await alice.open("/confidencialidade")
            await alice.should_see("A sua chave de verdade", retries=50)

            # 1. a chave sendo criada: a privada de verdade está no keystore, cifrada; um par nasce na tela
            await alice.should_see("-----BEGIN ENCRYPTED PRIVATE KEY-----")
            await alice.should_see("Pública: o servidor tem exatamente esta")
            alice.find(marker="conf-gerar").click()
            await alice.should_see("voltou o mesmo número: o par funciona ✓", retries=100)
            await alice.should_see("O par se divide")

            # 2. a chave compartilhada: as públicas conferem e o número da dupla é o que Bob também calcula
            diretorio = await bob.sessao.api.buscar_chaves(["alice", "bob"], "real")
            numero = conf.numero_conversa(diretorio.chaves["alice"].fingerprint, diretorio.chaves["bob"].fingerprint)
            await alice.should_see("Número de segurança de @alice e @bob")
            await alice.should_see(numero.split()[0])
            await alice.should_see("públicas conferidas com @bob")
            await alice.should_see("privada de @bob fica aqui")

            # 3. evidências: os bytes que Bob recebeu têm o mesmo resumo que Alice mostra; nem ela abre o envelope dele
            await alice.should_see(_agrupado(conf.resumo_cifrado(recebido)))
            await alice.should_see(_agrupado(conf.resumo_texto("so nos dois")))
            await alice.should_see("Nem este aparelho abre o envelope de @bob")
            await alice.should_see("@bob recebeu e confirmou", retries=50)
            alice.find(marker="conf-tentar-ler").click()
            await alice.should_see("nenhum bloco abriu", retries=100)

            await alice.open("/")
            await alice.should_see("Provar a confidencialidade", retries=50)
    finally:
        await bob.desconectar()
        await bob.sessao.api.fechar()
