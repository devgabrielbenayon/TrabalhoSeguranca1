"""Cliente HTTP do app para o back-end. Só trafegam chaves públicas e envelopes cifrados."""

from __future__ import annotations

from typing import Any, Iterable

import httpx

from shared.schemas import (
    ChavePublicaOut,
    ClienteEdicaoIn,
    ClienteOut,
    ConversaIn,
    ConversaOut,
    DesafioOut,
    DiretorioOut,
    Envelope,
    EstatisticasOut,
    EventoTransitoOut,
    ExclusaoChaveIn,
    Modo,
    RegistroIn,
    RegistroOut,
    ServidorIn,
    ServidorOut,
    TokenOut,
    TopologiaOut,
    TrocaChaveIn,
    UsuarioOut,
)


class ErroApi(Exception):
    def __init__(self, status: int, detalhe: Any) -> None:
        super().__init__(f"{status}: {detalhe}")
        self.status, self.detalhe = status, detalhe


class ApiCliente:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        event_hooks: dict | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=15, event_hooks=event_hooks)
        self.token: str | None = None

    async def fechar(self) -> None:
        await self._http.aclose()

    async def _req(self, metodo: str, url: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resposta = await self._http.request(metodo, url, headers=headers, **kwargs)
        if resposta.status_code >= 400:
            try:
                detalhe = resposta.json().get("detail", resposta.text)
            except ValueError:
                detalhe = resposta.text
            raise ErroApi(resposta.status_code, detalhe)
        return resposta.json() if resposta.content else None

    # ------------------------------------------------------------ Passo 0 e sessão

    async def registrar(self, dados: RegistroIn) -> RegistroOut:
        return RegistroOut.model_validate(await self._req("POST", "/api/auth/register", json=dados.model_dump()))

    async def login(self, username: str, senha: str) -> TokenOut:
        resposta = TokenOut.model_validate(
            await self._req("POST", "/api/auth/login", json={"username": username, "senha": senha})
        )
        self.token = resposta.token
        return resposta

    async def logout(self) -> None:
        if self.token:
            await self._req("POST", "/api/auth/logout")
            self.token = None

    async def eu(self) -> UsuarioOut:
        return UsuarioOut.model_validate(await self._req("GET", "/api/me"))

    # ------------------------------------------------------------ diretório de chaves

    async def buscar_chaves(self, usuarios: Iterable[str], modo: Modo = "real") -> DiretorioOut:
        params = {"users": ",".join(usuarios), "modo": modo}
        return DiretorioOut.model_validate(await self._req("GET", "/api/keys", params=params))

    async def minhas_chaves(self) -> list[ChavePublicaOut]:
        return [ChavePublicaOut.model_validate(c) for c in await self._req("GET", "/api/me/keys")]

    async def chave_por_id(self, key_id: str) -> ChavePublicaOut:
        return ChavePublicaOut.model_validate(await self._req("GET", f"/api/keys/id/{key_id}"))

    async def desafio(self) -> DesafioOut:
        return DesafioOut.model_validate(await self._req("POST", "/api/keys/challenge"))

    async def trocar_chave(self, dados: TrocaChaveIn) -> ChavePublicaOut:
        return ChavePublicaOut.model_validate(await self._req("PUT", "/api/me/key", json=dados.model_dump()))

    async def excluir_chave(self, dados: ExclusaoChaveIn) -> None:
        await self._req("POST", "/api/me/key/revoke", json=dados.model_dump())

    # ------------------------------------------------------------ conversas

    async def criar_conversa(self, participantes: list[str], modo: Modo) -> ConversaOut:
        dados = ConversaIn(participantes=participantes, modo=modo)
        return ConversaOut.model_validate(await self._req("POST", "/api/conversations", json=dados.model_dump()))

    async def conversas(self) -> list[ConversaOut]:
        return [ConversaOut.model_validate(c) for c in await self._req("GET", "/api/conversations")]

    async def historico(self, conversation_id: int) -> list[Envelope]:
        envelopes = await self._req("GET", "/api/messages", params={"conversation_id": conversation_id})
        return [Envelope.model_validate(e) for e in envelopes]

    # ------------------------------------------------------------ clientes (RF12)

    async def clientes(self) -> list[ClienteOut]:
        return [ClienteOut.model_validate(c) for c in await self._req("GET", "/api/clients")]

    async def editar_cliente(self, client_id: int, dados: ClienteEdicaoIn) -> ClienteOut:
        corpo = dados.model_dump(exclude_unset=True)
        return ClienteOut.model_validate(await self._req("PUT", f"/api/clients/{client_id}", json=corpo))

    async def remover_cliente(self, client_id: int, senha: str | None = None) -> None:
        await self._req("DELETE", f"/api/clients/{client_id}", json={"senha": senha} if senha else None)

    # ------------------------------------------------------------ servidores / nós (RF13)

    async def servidores(self) -> list[ServidorOut]:
        return [ServidorOut.model_validate(s) for s in await self._req("GET", "/api/servers")]

    async def topologia(self) -> TopologiaOut:
        return TopologiaOut.model_validate(await self._req("GET", "/api/servers/topology"))

    async def criar_servidor(self, dados: ServidorIn) -> ServidorOut:
        return ServidorOut.model_validate(await self._req("POST", "/api/servers", json=dados.model_dump()))

    async def editar_servidor(self, server_id: int, dados: ServidorIn) -> ServidorOut:
        return ServidorOut.model_validate(await self._req("PUT", f"/api/servers/{server_id}", json=dados.model_dump()))

    async def status_servidor(self, server_id: int, ativo: bool) -> ServidorOut:
        return ServidorOut.model_validate(await self._req("PATCH", f"/api/servers/{server_id}/status", json={"ativo": ativo}))

    async def remover_servidor(self, server_id: int) -> None:
        await self._req("DELETE", f"/api/servers/{server_id}")

    async def topologia_exemplo(self) -> list[ServidorOut]:
        return [ServidorOut.model_validate(s) for s in await self._req("POST", "/api/servers/example")]

    # ------------------------------------------------------------ painéis

    async def rastro(self, message_id: str) -> list[EventoTransitoOut]:
        return [EventoTransitoOut.model_validate(e) for e in await self._req("GET", f"/api/trace/{message_id}")]

    async def estatisticas(self) -> EstatisticasOut:
        return EstatisticasOut.model_validate(await self._req("GET", "/api/stats"))

    async def adulteracao(self) -> bool:
        return (await self._req("GET", "/api/demo/tamper"))["ativo"]

    async def armar_adulteracao(self, ativo: bool) -> bool:
        return (await self._req("PUT", "/api/demo/tamper", json={"ativo": ativo}))["ativo"]
