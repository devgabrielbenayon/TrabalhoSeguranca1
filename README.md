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

1. **Back-end** (API + relay, porta 8000, com TLS): `python -m backend`
   Na primeira execução são gerados em `data/tls/` uma autoridade certificadora local (`ca.pem`) e o certificado
   do servidor; o front-end confia só nessa AC. Num banco novo já são criados quatro nós de exemplo (Manaus,
   São Paulo, Brasília e Recife). Documentação da API: https://127.0.0.1:8000/docs (o navegador avisa que a AC
   é desconhecida, porque ela é local).
   Sem TLS, só para depurar: `uvicorn backend.main:app --reload` e `$env:CRIPTOCHAT_API = "http://127.0.0.1:8000"`
   nos front-ends.
2. **Aparelho da primeira pessoa** (porta 8080): `python -m frontend.main` e abra http://127.0.0.1:8080
   O primeiro cadastro vira administrador (vê o Observador e altera nós e clientes).
3. **Aparelho da segunda pessoa** (outro terminal):

   ```powershell
   $env:CRIPTOCHAT_PORTA = "8081"; $env:CRIPTOCHAT_KEYSTORE = "data/keystore2"
   python -m frontend.main
   ```

Cada processo do front-end é um aparelho: as chaves privadas ficam só no keystore dele (`data/keystore…`).

Variáveis de ambiente: `CRIPTOCHAT_API` (URL do back-end; padrão `https://127.0.0.1:8000`), `CRIPTOCHAT_CA`
(AC em que o front-end confia; padrão `data/tls/ca.pem`), `CRIPTOCHAT_PORTA`, `CRIPTOCHAT_HOST`,
`CRIPTOCHAT_KEYSTORE`, `CRIPTOCHAT_DB` (banco do back-end; padrão `sqlite:///data/criptochat.db`),
`CRIPTOCHAT_API_HOST`, `CRIPTOCHAT_API_PORTA` e `CRIPTOCHAT_TLS` (pasta dos certificados do back-end).

## Proteções do canal e do login

- **TLS 1.3** entre front-end e back-end (`https://` e `wss://`): senha, token e metadados não trafegam em claro.
- **Token fora da URL:** o WebSocket recebe o token na primeira mensagem (`{"type": "auth", "token": …}`), não em
  `/ws?token=…`, onde ele ficaria em logs de acesso e de proxies. Canal sem autenticação em 10 s é fechado.
- **Limite de tentativas de login:** 5 falhas em 15 minutos por usuário (ou 20 por IP) bloqueiam novas tentativas
  com HTTP 429 e `Retry-After`, até a falha mais antiga sair da janela.
- **Mesmo tempo de resposta** para usuário inexistente e senha errada: o argon2 roda nos dois casos.

## Telas

| Tela | O que mostra |
|---|---|
| Início | Contadores, estado do aparelho e o roteiro da demonstração |
| Chat | Conversas 1:1 e em grupo; entrega e assinatura como ícones (o detalhe aparece ao passar o mouse), fila "sem caminho", contador de caracteres e atalhos para o Inspetor e o Caminho |
| Confidencialidade | O pilar em três provas: (1) a chave sendo criada — um par RSA nasce número a número (p, q, n, φ, e, d) e a privada real aparece no keystore, cifrada; (2) a chave compartilhada — animação das públicas indo ao diretório e ao outro aparelho, conferência dos fingerprints e número de segurança da dupla; (3) evidências dos dois lados — remetente, servidor e destinatário lado a lado, com códigos coloridos (SHA-256) que saem iguais nas telas dos dois aparelhos |
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
