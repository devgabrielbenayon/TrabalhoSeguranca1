"""Estado do "aparelho": quem está logado, o keystore e as operações de conta.

Cada processo do front-end representa um aparelho com um usuário por vez (para dois usuários,
suba dois processos em portas diferentes). Fica fora das páginas para poder ser testado sem UI.
"""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from frontend.api_client import ApiCliente, ErroApi
from frontend.keystore import Keystore
from shared.crypto import rsa_didatico, rsa_real
from shared.crypto.chaves import ChavePrivada
from shared.crypto.prova import mensagem_prova
from shared.crypto.rsa_didatico import GeracaoDidatica
from shared.schemas import ChavePublicaIn, ChavePublicaOut, ExclusaoChaveIn, Modo, RegistroIn, RegistroOut, TrocaChaveIn, UsuarioOut
from shared.trace import Tracer

RAIZ_KEYSTORE = Path(os.environ.get("CRIPTOCHAT_KEYSTORE", "data/keystore"))


class Sessao:
    def __init__(self, api: ApiCliente, raiz_keystore: Path | str = RAIZ_KEYSTORE) -> None:
        self.api = api
        self.raiz_keystore = Path(raiz_keystore)
        self.usuario: UsuarioOut | None = None
        self.keystore: Keystore | None = None
        self.tracer = Tracer("cliente")  # o Inspetor (fase 7) assina este rastro
        self.ao_sair: list[Callable[[], Awaitable[None]]] = []  # ex.: fechar o WebSocket

    @property
    def logado(self) -> bool:
        return self.usuario is not None

    @property
    def admin(self) -> bool:
        return self.usuario is not None and self.usuario.is_admin

    async def cadastrar(self, username: str, nome: str, senha: str, bits_didatico: int = 32) -> tuple[RegistroOut, GeracaoDidatica]:
        """Passo 0: gera os pares (real e didático), publica só as públicas com prova de posse,
        guarda as privadas no keystore e já entra na conta."""
        username = username.strip().lower()
        self.tracer.ator = username

        with self.tracer.etapa("geracao_chaves", entrada={"modo": "didatico", "bits": bits_didatico}) as ev:
            geracao = rsa_didatico.gerar_parametros(bits_didatico)
            didatica = geracao.privada()
            ev.saida = {"key_id": didatica.publica.key_id}
            ev.detalhes = asdict(geracao)  # p, q, φ e d: só no rastro local, para a animação

        with self.tracer.etapa("geracao_chaves", entrada={"modo": "real", "bits": rsa_real.BITS_PADRAO}) as ev:
            real = await asyncio.to_thread(rsa_real.gerar)
            ev.saida = {"key_id": real.publica.key_id}
            ev.detalhes = {"e": real.publica.numeros["e"], "bits_n": real.publica.numeros["n"].bit_length()}

        privadas: list[ChavePrivada] = [real, didatica]
        with self.tracer.etapa("prova_de_posse", entrada=[p.publica.key_id for p in privadas]) as ev:
            chaves = [self._chave_com_prova(p, username) for p in privadas]
            ev.saida = [c.prova for c in chaves]

        registro = await self.api.registrar(RegistroIn(username=username, nome=nome, senha=senha, chaves=chaves))

        keystore = Keystore(self.raiz_keystore, username, senha)
        for privada in privadas:
            keystore.guardar(privada)

        await self.entrar(username, senha)
        return registro, geracao

    async def entrar(self, username: str, senha: str) -> bool:
        """Faz login. Devolve False se este aparelho não tiver as privadas do usuário."""
        username = username.strip().lower()
        token = await self.api.login(username, senha)
        self.usuario = token.usuario
        self.keystore = Keystore(self.raiz_keystore, username, senha)
        self.tracer.ator = username
        return self.keystore.existe()

    async def trocar_chave(self, modo: Modo, bits_didatico: int | None = None) -> tuple[ChavePublicaOut, GeracaoDidatica | None]:
        """Fluxo 5.4: novo par, desafio do servidor assinado com a NOVA privada, antiga fica no keystore."""
        username = self.usuario.username
        geracao = None
        with self.tracer.etapa("geracao_chaves", entrada={"modo": modo, "motivo": "troca"}) as ev:
            if modo == "didatico":
                atual = self.keystore.ativa("didatico")
                bits = bits_didatico or (atual.n.bit_length() if atual else 32)
                geracao = rsa_didatico.gerar_parametros(bits)
                privada: ChavePrivada = geracao.privada()
                ev.detalhes = asdict(geracao)
            else:
                privada = await asyncio.to_thread(rsa_real.gerar)
            ev.saida = {"key_id": privada.publica.key_id}

        # guarda antes de publicar: se a resposta se perder, a privada nova não se perde junto
        self.keystore.guardar(privada, ativa=False)
        desafio = await self.api.desafio()
        with self.tracer.etapa("prova_de_posse", entrada={"nonce": desafio.nonce, "key_id": privada.publica.key_id}) as ev:
            assinatura = privada.assinar(mensagem_prova("troca", username, privada.publica.key_id, desafio.nonce))
            prova = ev.saida = base64.b64encode(assinatura).decode("ascii")
        saida = await self.api.trocar_chave(
            TrocaChaveIn(modo=modo, public_key=privada.publica.exportar(), nonce=desafio.nonce, prova=prova)
        )
        self.keystore.ativar(privada.publica.key_id)
        return saida, geracao

    async def excluir_chave(self, modo: Modo, senha: str, apagar_privadas: bool = False) -> None:
        """Fluxo 5.5: o servidor revoga a chave. Localmente, a privada deixa de ser a ativa —
        ou é apagada, e aí as mensagens antigas desse modo ficam ilegíveis para sempre."""
        await self.api.excluir_chave(ExclusaoChaveIn(modo=modo, senha=senha))
        if apagar_privadas:
            self.keystore.apagar_modo(modo)
        else:
            self.keystore.desativar(modo)

    async def sair(self) -> None:
        """Sai mesmo com o servidor fora do ar: o estado local é limpo de qualquer jeito."""
        for acao in self.ao_sair:
            await acao()
        try:
            await self.api.logout()
        except (ErroApi, httpx.HTTPError):
            self.api.token = None
        self.usuario = None
        self.keystore = None
        self.tracer.eventos.clear()  # o rastro local tem texto claro: não fica para o próximo usuário

    @staticmethod
    def _chave_com_prova(privada: ChavePrivada, username: str) -> ChavePublicaIn:
        assinatura = privada.assinar(mensagem_prova("registro", username, privada.publica.key_id))
        return ChavePublicaIn(
            modo=privada.modo,
            public_key=privada.publica.exportar(),
            prova=base64.b64encode(assinatura).decode("ascii"),
        )
