# TrabalhoSegurança1

Repositório para o desenvolvimento do Trabalho 1 da disciplina de Segurança.

**CriptoChat RSA**: mensageiro ponta a ponta com RSA puro (modo didático, implementado do zero, e modo real com
`cryptography`), CRUD de clientes e de nós de retransmissão, e telas que mostram cada passo da criptografia.
O plano completo está em [docs/PLANO_IMPLEMENTACAO.md](docs/PLANO_IMPLEMENTACAO.md).

## Como executar

Requer Python 3.11+. Todos os comandos rodam a partir da raiz do repositório.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # no Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

1. **Back-end** (API + relay, porta 8000): `uvicorn backend.main:app --reload`
   Num banco novo já são criados quatro nós de exemplo (Manaus, São Paulo, Brasília e Recife).
   Documentação da API: http://127.0.0.1:8000/docs
2. **Aparelho da primeira pessoa** (porta 8080): `python -m frontend.main` e abra http://127.0.0.1:8080
   O primeiro cadastro vira administrador (vê o Observador e altera nós e clientes).
3. **Aparelho da segunda pessoa** (outro terminal):

   ```powershell
   $env:CRIPTOCHAT_PORTA = "8081"; $env:CRIPTOCHAT_KEYSTORE = "data/keystore2"
   python -m frontend.main
   ```

Cada processo do front-end é um aparelho: as chaves privadas ficam só no keystore dele (`data/keystore…`).

Variáveis de ambiente: `CRIPTOCHAT_API` (URL do back-end), `CRIPTOCHAT_PORTA`, `CRIPTOCHAT_HOST`,
`CRIPTOCHAT_KEYSTORE` e `CRIPTOCHAT_DB` (banco do back-end; padrão `sqlite:///data/criptochat.db`).

## Telas

| Tela | O que mostra |
|---|---|
| Início | Contadores, estado do aparelho e o roteiro da demonstração |
| Chat | Conversas 1:1 e em grupo; status de entrega, assinatura verificada, fila "sem caminho" e atalho para o Inspetor |
| Minhas chaves | Trocar e excluir chave, histórico, keystore local (apagar privada) e diretório de chaves públicas |
| Inspetor | Raio-X de uma mensagem: blocos, mᵉ mod n, assinatura, saltos na rede, cᵈ mod n, tabela square-and-multiply, linha do tempo e experimentos (chave errada, bit adulterado) |
| Observador (admin) | Caminho animado do envelope pelos nós, tráfego ao vivo, visão do servidor e do interceptador (que quebra chaves didáticas e lê a mensagem) e adulteração de demonstração |
| Clientes | CRUD: busca, edição do perfil, mudança de nó, promoção, remoção (revoga as chaves) e reativação |
| Servidores | CRUD de nós e ligações; desligar um nó recalcula o caminho ou deixa a mensagem na fila |
| Laboratório | Quebrar uma chave fatorando n, e gráficos de tempo por tamanho de chave e de custo da fatoração |

## Testes

```powershell
pytest
```

## Autor

Gabriel Benayon
