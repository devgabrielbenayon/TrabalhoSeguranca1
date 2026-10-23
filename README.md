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
| Chat | Conversas 1:1 e em grupo; entrega e assinatura como ícones (o detalhe aparece ao passar o mouse), fila "sem caminho", contador de caracteres e atalhos para o Inspetor e o Caminho |
| Inspetor | Uma mensagem em 7 passos — aparelho de quem envia, rede, aparelho de quem recebe —, com os valores reais ao abrir cada passo (blocos RSA-OAEP, assinatura RSA-PSS), "quem vê o quê" e experimentos (chave errada, bit adulterado) |
| Caminho da mensagem | O envelope animado sobre a topologia, por destinatário, até a confirmação de entrega. Qualquer usuário, para as próprias mensagens |
| Minhas chaves | Onde cada chave fica (aparelho, servidor, contatos), as duas metades do par, o ciclo de vida (troca, exclusão, apagar privada) e o diretório de chaves públicas |
| Observador (admin) | Tráfego de todos ao vivo: caminho animado, visão do servidor e do interceptador e adulteração de demonstração |
| Clientes | CRUD: busca, edição do perfil, mudança de nó, promoção, remoção (revoga as chaves) e reativação |
| Servidores | CRUD de nós e ligações; desligar um nó recalcula o caminho ou deixa a mensagem na fila |

As telas usam só o modo real (RSA 2048 bits). O modo didático (RSA de livro com números pequenos) continua no código
e nos testes, mas não aparece: não dá para criar conversas nele, e conversas didáticas antigas ficam ocultas. O
Laboratório (quebrar uma chave didática fatorando n) saiu do menu, mas continua disponível em `/laboratorio`.

## Testes

```powershell
pytest
```

## Autor

Gabriel Benayon
