# Ambiente e execução: preparação da gravação

Guia prático para montar o ambiente do vídeo no **Windows 11 com PowerShell**, o sistema desta máquina.
Todos os comandos partem da raiz do repositório:

```powershell
cd "C:\Users\enzop\OneDrive\Área de Trabalho\Seguranca\TrabalhoSeguranca1"
```

> **Leia antes de tudo: como o cliente funciona.** O "cliente" do CriptoChat **não é JavaScript no navegador**.
> É um processo Python com NiceGUI ([frontend/main.py:1-5](../../frontend/main.py#L1-L5)), e o navegador só desenha a
> tela. Toda a criptografia (gerar a chave, cifrar, assinar, decifrar) roda nesse processo Python. É ele, e não o
> navegador, que fala com o back-end por HTTP e WebSocket ([frontend/mensageiro.py:140](../../frontend/mensageiro.py#L140)).
>
> Três consequências práticas:
> 1. **Um usuário = um processo = uma porta.** A sessão é um objeto global do processo
>    ([frontend/main.py:22](../../frontend/main.py#L22)), então dois navegadores na mesma porta mostram o **mesmo**
>    usuário. Navegadores ou perfis diferentes servem só para diferenciar as janelas visualmente.
> 2. **A chave privada fica em arquivo**, na pasta do keystore do processo
>    ([frontend/keystore.py:3-8](../../frontend/keystore.py#L3-L8)). Não fica em localStorage nem em IndexedDB.
> 3. **DevTools > Network não mostra o cifrado.** O que o navegador recebe do NiceGUI é a tela já renderizada, com o
>    texto claro, como a tela de um celular. O cifrado em trânsito aparece no **Wireshark** (seção 3), na
>    porta 8000, e na tela **Observador**. O cifrado em repouso aparece no **banco SQLite**.

> **Só o modo real (RSA 2048) aparece nas telas.** O modo didático foi retirado da interface
> ([frontend/pages/layout.py:30-31](../../frontend/pages/layout.py#L30-L31), [README.md:49-51](../../README.md#L49-L51)).
> **Atenção:** o cadastro ainda gera e publica, por baixo, um par didático de 32 bits para cada usuário
> ([frontend/sessao.py:53-57](../../frontend/sessao.py#L53-L57), [:64-73](../../frontend/sessao.py#L64-L73)). Ele nunca
> é usado pelas telas, mas aparece no banco (uma linha `modo = didatico` por usuário em `public_keys`) e no keystore
> (um arquivo `k_….json`). Por isso, todas as consultas deste guia **filtram `modo = 'real'`**. Se quiser mostrar ou
> explicar esse resíduo, veja a seção 2.6.3.

---

## 1. Setup inicial (uma vez)

### 1.1 Dependências

Requer Python ≥ 3.11 ([pyproject.toml](../../pyproject.toml)); esta máquina tem o 3.12.10.

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Confira que está tudo certo rodando os testes (todos devem passar):

```powershell
python -m pytest -q
```

### 1.2 Banco de dados

Não há servidor de banco: é um **SQLite** em `data\criptochat.db`, criado sozinho quando o back-end sobe. A pasta é
criada em [backend/db.py:34](../../backend/db.py#L34) e as tabelas em [backend/main.py:19-20](../../backend/main.py#L19-L20).
Num banco vazio, o back-end também cria os 4 nós de exemplo: Manaus, São Paulo, Brasília e Recife
([backend/main.py:25-29](../../backend/main.py#L25-L29)).

Para ter um **banco limpo**, apague a pasta `data\` (seção 7). Comece a gravação sempre com banco limpo.

### 1.3 Variáveis de ambiente

| Variável | Quem lê | Padrão | Uso no vídeo |
|---|---|---|---|
| `CRIPTOCHAT_DB` | back-end ([backend/db.py:15](../../backend/db.py#L15)) | `sqlite:///data/criptochat.db` | não mexer |
| `CRIPTOCHAT_API` | front-end ([frontend/main.py:17-18](../../frontend/main.py#L17-L18)) | `http://127.0.0.1:8000` | não mexer. É assim que o cliente encontra o servidor (o `ws://…/ws` é derivado dela) |
| `CRIPTOCHAT_PORTA` | front-end ([frontend/main.py:19](../../frontend/main.py#L19)) | `8080` | 8080, 8081 e 8082 |
| `CRIPTOCHAT_HOST` | front-end ([frontend/main.py:20](../../frontend/main.py#L20)) | `127.0.0.1` | não mexer |
| `CRIPTOCHAT_KEYSTORE` | front-end ([frontend/main.py:22](../../frontend/main.py#L22)) | `data/keystore` | `data/keystoreA`, `B` e `C` |

`$env:...` vale só no terminal onde foi definido. Por isso, **um terminal por processo**.

### 1.4 Ferramentas de evidência

- **Wireshark**, já instalado em `C:\Program Files\Wireshark`. A configuração e o uso estão na seção 3.
- **Consultas no banco**: o `sqlite3.exe` não está instalado. Use a função `sql` da seção 2.6 (Python puro) ou a
  extensão *SQLite Viewer* do VS Code (abrindo `data\criptochat.db`).
- **VS Code** com o repositório aberto e zoom legível (`Ctrl` + `=` duas vezes).

---

## 2. Subindo cada componente: um terminal por processo

Em **todos** os terminais, primeiro:

```powershell
cd "C:\Users\enzop\OneDrive\Área de Trabalho\Seguranca\TrabalhoSeguranca1"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Dica: use o Windows Terminal com 6 abas nomeadas (clique com o botão direito na aba → *Renomear*): `backend`,
`alice`, `bruno`, `carla`, `sql` e `extra`.

### 2.1 Terminal `backend`: API e relay (porta 8000)

```powershell
uvicorn backend.main:app --port 8000
```

Está funcionando quando aparece:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Para conferir: `Invoke-RestMethod http://127.0.0.1:8000/api/health` deve responder `status: ok`. A documentação
Swagger fica em http://127.0.0.1:8000/docs e é útil na cena de arquitetura. O README usa `--reload`; para gravar,
prefira **sem** ele, para evitar reinícios inesperados.

> As portas 9001–9004 que aparecem nos nós (Manaus etc.) são **lógicas** ([backend/nos.py:28-33](../../backend/nos.py#L28-L33)):
> nada escuta nelas. Todos os nós vivem dentro deste back-end, e todo o tráfego de rede passa pela porta **8000**.

### 2.2 Terminal `alice`: aparelho da Alice (porta 8080)

```powershell
$env:CRIPTOCHAT_PORTA = "8080"; $env:CRIPTOCHAT_KEYSTORE = "data/keystoreA"
python -m frontend.main
```

Está funcionando quando aparece `NiceGUI ready to go on http://127.0.0.1:8080`. Depois, abra http://127.0.0.1:8080.

### 2.3 Terminal `bruno`: aparelho do Bruno (porta 8081)

```powershell
$env:CRIPTOCHAT_PORTA = "8081"; $env:CRIPTOCHAT_KEYSTORE = "data/keystoreB"
python -m frontend.main
```

### 2.4 Terminal `carla`: aparelho da Carla (porta 8082)

```powershell
$env:CRIPTOCHAT_PORTA = "8082"; $env:CRIPTOCHAT_KEYSTORE = "data/keystoreC"
python -m frontend.main
```

### 2.5 Ordem de subida

1. `backend`, sempre primeiro.
2. **Wireshark capturando** (seção 3.3). Tem de começar **antes** de qualquer login, para enxergar a abertura dos
   WebSockets.
3. `alice`, `bruno` e `carla`, em qualquer ordem.
4. Os três navegadores (seção 4).

Se o back-end cair e voltar, os aparelhos **reconectam sozinhos** ([frontend/mensageiro.py:162-180](../../frontend/mensageiro.py#L162-L180)).

### 2.6 Terminal `sql`: consultas no banco

#### 2.6.1 A função `sql`

Cole esta função **uma vez** no terminal `sql`. Ela vive só nessa sessão do PowerShell:

```powershell
function sql([string]$q, [int]$w = 70) {
  $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@"
import sqlite3
con = sqlite3.connect('data/criptochat.db')
cur = con.execute('''$q''')
cols = [d[0] for d in cur.description]
print(' | '.join(cols)); print('-' * 100)
for r in cur: print(' | '.join(str(x)[:$w] for x in r))
"@ | python -
}
```

Para testar: `sql "SELECT name FROM sqlite_master WHERE type='table'"`.
O segundo parâmetro é a largura máxima de cada coluna, por exemplo `sql "SELECT conteudo FROM envelopes" 400`.

#### 2.6.2 Consultas que você vai usar (copie conforme a cena)

```powershell
# usuários e quem é admin
sql "SELECT id, username, nome, is_admin, server_id, ativo FROM clients"

# o esquema da tabela de chaves: NÃO existe coluna de chave privada
sql "SELECT name, type FROM pragma_table_info('public_keys')"

# as chaves públicas publicadas (modo real)
sql "SELECT c.username, k.key_id, k.status, k.criada_em, substr(k.public_key,1,40) AS publica FROM public_keys k JOIN clients c ON c.id = k.client_id WHERE k.modo = 'real' ORDER BY k.id"

# as chaves de um usuário (troque o nome)
sql "SELECT k.key_id, k.status, k.criada_em, k.substituida_em FROM public_keys k JOIN clients c ON c.id = k.client_id WHERE c.username = 'bruno' AND k.modo = 'real'"

# auditoria do ciclo de vida (modo real)
sql "SELECT c.username, e.tipo, e.key_id, e.ts FROM key_events e JOIN clients c ON c.id = e.client_id JOIN public_keys k ON k.key_id = e.key_id WHERE k.modo = 'real' ORDER BY e.id"

# quem buscou a chave de quem (define quem é avisado na troca e na exclusão)
sql "SELECT a.username AS quem_buscou, o.username AS dono, k.key_id FROM key_access k JOIN clients a ON a.id = k.client_id JOIN clients o ON o.id = k.owner_id"

# desafios (nonce) da troca de chave
sql "SELECT nonce, client_id, usado, expira_em FROM key_challenges"

# a tabela messages NÃO tem coluna de texto
sql "SELECT name FROM pragma_table_info('messages')"

# envelopes guardados: um por destinatário, só o cifrado
sql "SELECT e.id, substr(e.message_id,1,8) AS msg, c.username AS para, e.to_key_id, e.status, substr(e.conteudo,1,90) AS conteudo FROM envelopes e JOIN clients c ON c.id = e.recipient_id ORDER BY e.id DESC LIMIT 6"

# um envelope inteiro (troque o id)
sql "SELECT conteudo FROM envelopes WHERE id = 1" 2000

# rastro do servidor (o que ele registrou do trânsito)
sql "SELECT etapa, ator, entrada, saida FROM trace_events ORDER BY id DESC LIMIT 8" 60

# sessões: só o SHA-256 do token
sql "SELECT token_hash, client_id, expira_em FROM sessoes"
```

Prova de que o texto não está no banco (procura o texto dentro do arquivo binário e não deve achar nada):

```powershell
Select-String -Path .\data\criptochat.db -Pattern "biblioteca" -SimpleMatch
Select-String -Path .\data\criptochat.db -Pattern "PRIVATE KEY" -SimpleMatch
Select-String -Path .\data\criptochat.db -Pattern "BEGIN PUBLIC KEY" -SimpleMatch | Select-Object -First 1
```

As duas primeiras não devem imprimir nada; a terceira imprime uma linha (as públicas estão lá).
Use mensagens **sem acento** nessa prova, por exemplo "Encontro as 15h na biblioteca".

Ver o keystore de um aparelho:

```powershell
Get-ChildItem .\data\keystoreA\alice\*.pem
Get-ChildItem .\data\keystoreA\alice\*.pem | Select-Object -First 1 | Get-Content -TotalCount 3
```

O `.pem` começa com `-----BEGIN ENCRYPTED PRIVATE KEY-----`, porque é cifrado com a senha do usuário
([shared/crypto/rsa_real.py:80-86](../../shared/crypto/rsa_real.py#L80-L86)).

#### 2.6.3 O resíduo do modo didático (para não ser pego de surpresa)

Sem o filtro `modo = 'real'`, cada usuário aparece com **duas** chaves públicas, e o keystore tem também um `.json`:

```powershell
sql "SELECT c.username, k.modo, k.key_id, k.status FROM public_keys k JOIN clients c ON c.id = k.client_id ORDER BY k.id"
Get-ChildItem .\data\keystoreA\alice
```

A linha `didatico` é a chave de 32 bits que o cadastro ainda gera ([frontend/sessao.py:53-57](../../frontend/sessao.py#L53-L57)).
Nenhuma tela cria conversa nesse modo ([frontend/pages/chat.py](../../frontend/pages/chat.py) usa sempre `MODO = "real"`),
e conversas didáticas antigas ficam ocultas ([frontend/pages/layout.py:292-294](../../frontend/pages/layout.py#L292-L294)).
O `.json` guarda o `d` dessa chave **em claro** ([shared/crypto/rsa_didatico.py:227-229](../../shared/crypto/rsa_didatico.py#L227-L229)).
Se o professor perguntar, a resposta está no [guia-de-estudo.md](guia-de-estudo.md), pergunta 19.

---

## 3. Wireshark passo a passo

O Wireshark "escuta" a placa de rede e mostra cada pacote. Aqui tudo roda na mesma máquina, então a captura é feita
na interface de **loopback**, o tráfego de `127.0.0.1` para `127.0.0.1`. Ele serve para provar três coisas:
1. o cadastro só envia a chave **pública**;
2. a mensagem trafega **cifrada**;
3. a palavra `PRIVATE` não aparece em nenhum pacote.

### 3.1 Verificar o suporte a loopback (uma vez)

1. Abra o Wireshark (menu Iniciar → *Wireshark*).
2. A tela inicial lista as interfaces, cada uma com um pequeno gráfico de atividade ao lado. Procure
   **Adapter for loopback traffic capture**.
3. **Se não aparecer**, o Npcap foi instalado sem suporte a loopback. Baixe o instalador em https://npcap.com,
   execute, marque **"Support loopback traffic ("Npcap Loopback Adapter" will be created)"** e reinicie o Wireshark.

### 3.2 Configurar o Wireshark (uma vez)

**a) Tratar a porta 8000 como HTTP.** O Wireshark só reconhece HTTP sozinho em algumas portas. Sem isso, os pacotes
aparecem como "TCP" genérico e o WebSocket não é decodificado.
1. Menu **Analyze** → **Decode As…**
2. Clique no **+** (canto inferior esquerdo da janela).
3. Na linha criada: coluna *Field* = `TCP port`; *Value* = `8000`; *Current* = `HTTP` (clique na célula para abrir a
   lista).
4. Clique em **Save** e depois em **OK**.

**b) Mostrar o texto do WebSocket como JSON (árvore expansível).**
1. Menu **Edit** → **Preferences…** → no painel esquerdo, **Protocols** → role até **WebSocket** (digitar "WebSocket"
   com a lista focada ajuda a achar).
2. Em **Dissect websocket text as**, escolha **JSON** → **OK**.
3. Se a sua versão não tiver essa opção, o conteúdo aparece como *Line-based text data*. Funciona igual, só que sem a
   árvore.

**c) Deixar legível para o vídeo.**
- **View** → **Zoom In** (`Ctrl` + `+`) duas ou três vezes.
- **View** → desmarque **Packet Bytes** se quiser mais espaço. O painel de bytes crus pouco ajuda aqui.

### 3.3 Iniciar a captura (a cada gravação)

1. Menu **Capture** → **Options…** (`Ctrl` + `K`).
2. Na aba *Input*, selecione a linha **Adapter for loopback traffic capture**.
3. Na coluna/campo **Capture Filter** dessa linha (ou na caixa "Capture filter for selected interfaces" embaixo),
   digite:

   ```
   tcp port 8000
   ```

   Ele fica verde quando está válido. **Por que filtrar:** o tráfego entre o navegador e o aparelho (portas 8080,
   8081 e 8082) carrega a tela já renderizada, **com o texto claro**. Isso é "dentro do aparelho", como a tela do
   celular, e não deve entrar na captura. A rede de verdade, entre o aparelho e o servidor, é a porta 8000.
4. Clique em **Start**.

Alternativa por linha de comando, no terminal `extra`:

```powershell
& "C:\Program Files\Wireshark\Wireshark.exe" -i "\Device\NPF_Loopback" -f "tcp port 8000" -k
```

> **Comece a captura antes dos logins.** O WebSocket começa com um pedido HTTP `Upgrade`. Se o Wireshark não viu
> esse início, os quadros aparecem como TCP sem decodificação. Se isso acontecer, no aparelho clique em **Sair** e
> **Entrar** de novo: o WebSocket é reaberto e passa a ser decodificado.

### 3.4 As três partes da janela

| Painel | Onde | Para que serve |
|---|---|---|
| **Lista de pacotes** | em cima | uma linha por pacote: nº, tempo, origem, destino, protocolo, tamanho e **Info** |
| **Detalhes** | no meio | o pacote selecionado em árvore; é aqui que se lê o conteúdo (clique nos ▶ para expandir) |
| **Bytes** | embaixo | os bytes crus em hexadecimal; não é necessário |

Na coluna **Info** você vai ver:
- `POST /api/auth/register HTTP/1.1 (application/json)`: um pedido REST;
- `HTTP/1.1 201 Created (application/json)`: a resposta;
- `WebSocket Text [FIN] [MASKED]`: um quadro **do aparelho para o servidor**. Pela regra do protocolo, os quadros que
  saem do cliente vão "mascarados" (XOR com 4 bytes); o Wireshark desfaz a máscara e mostra o conteúdo nos detalhes;
- `WebSocket Text [FIN]`: um quadro **do servidor para o aparelho**.

Dica para gravar: clique com o botão direito num pacote → **Show Packet in New Window** abre só aquele pacote numa
janela grande, fácil de mostrar.

### 3.5 Filtros de exibição (barra verde "Apply a display filter", logo acima da lista)

Digite o filtro e tecle `Enter`. Para voltar a ver tudo, clique no **X** da barra.

| Para ver | Filtro |
|---|---|
| todas as chamadas REST | `http` |
| o cadastro (público + prova) | `http.request.uri contains "/api/auth/register"` |
| a busca da chave pública de alguém, com a resposta | `http.request.uri contains "/api/keys" \|\| http.response_for.uri contains "/api/keys"` |
| troca e exclusão de chave | `http.request.uri contains "/api/me/key" \|\| http.request.uri contains "/api/keys/challenge"` |
| tudo, menos o login (que tem a senha em claro) | `(http \|\| websocket) && !(http.request.uri contains "/api/auth/login")` |
| todos os quadros de texto WebSocket | `websocket.opcode == 1` |
| só aparelho → servidor (`send`, `ack`) | `websocket.opcode == 1 && tcp.dstport == 8000` |
| só servidor → aparelho (`message`, `sent`, `delivered`, avisos de chave) | `websocket.opcode == 1 && tcp.srcport == 8000` |
| avisos de troca e exclusão de chave | `frame contains "key_changed" \|\| frame contains "key_revoked"` |

> `frame contains` procura nos bytes crus. Funciona para HTTP e para quadros **servidor → aparelho**, mas **não** para
> os quadros aparelho → servidor, que vão mascarados. Para esses, use o filtro por porta (`tcp.dstport == 8000`) e
> olhe o tamanho: o quadro do `send` é o maior (1 KB ou mais); os `ack` têm algumas dezenas de bytes.

### 3.6 Lendo um pacote: os três que aparecem no vídeo

**A) Cadastro: só a pública vai ao servidor**
1. Filtro `http.request.uri contains "/api/auth/register"` → `Enter`. Sobram 1 ou 3 pacotes (um por usuário cadastrado).
2. Clique no primeiro. Nos detalhes, expanda **JavaScript Object Notation: application/json** → **Object**.
3. Aparecem os membros `username`, `nome`, `senha`, `chaves`. Expanda **chaves** → **Array** → **Object**: há só
   `modo`, `public_key` (começa com `-----BEGIN PUBLIC KEY-----`) e `prova` (a assinatura em base64).
4. Mostre que **não existe** campo de chave privada.

> O `POST /api/auth/register` também mostra a `senha` em claro, porque não há TLS. Não deixe a câmera parar nesse
> campo, ou use isso de propósito na cena de limitações.
> Haverá **dois** objetos dentro de `chaves`: um `real` (PEM) e um `didatico` (`{"e":…,"n":…}`). É o resíduo explicado
> na seção 2.6.3. Mostre o objeto `real`.

**B) A mensagem A→B: o quadro `send`**
1. Filtro `websocket.opcode == 1 && tcp.dstport == 8000` → `Enter`.
2. Vá até o fim da lista (`End`) e clique no último quadro **grande** (coluna *Length* acima de ~1000), enviado logo
   depois que a Alice clicou em enviar. Os pequenos (algumas dezenas de bytes) são `ack`.
3. Nos detalhes: expanda **WebSocket** (você vê `Mask: True` e o *Masking-Key*) → **JavaScript Object Notation**
   (ou *Line-based text data*) → **Object**:
   - `type: "send"`, `message_id`, `conversation_id`;
   - **envelopes** → **Array** → dois **Object** (no grupo, três). Expanda um: `from: "alice"`, `to: "bruno"`,
     `to_key_id: "k_…"`, `mode: "real"`, `sent_at`, **blocks** (texto base64 longo) e `signature`.
4. O texto da mensagem **não aparece** em lugar nenhum.
5. Para mostrar o par: filtro `websocket.opcode == 1 && tcp.srcport == 8000` → o quadro `type: "message"` que o
   servidor mandou ao Bruno contém **só o envelope do Bruno**.

**C) Procurar a chave privada e o texto em toda a captura**
1. Deixe um filtro que mostre tudo da porta 8000, por exemplo `http || websocket`. A busca só olha os pacotes que
   estão sendo exibidos.
2. **Edit** → **Find Packet…** (`Ctrl` + `F`). Abre uma barra de busca acima da lista.
3. Ajuste os três seletores da barra, da esquerda para a direita:
   - **Packet details**: busca na árvore já decodificada, com a máscara do WebSocket desfeita. Não use
     *Packet bytes*: nos quadros mascarados os bytes crus estão embaralhados e a busca daria falso negativo;
   - **Narrow & Wide**;
   - **String**.
4. Digite `PRIVATE` → **Find**. A barra de status (embaixo) mostra
   **"No packet contains that string in its dissected display."**
5. Repita com `biblioteca` (a palavra da mensagem): também não acha.
6. Contraprova: procure `BEGIN PUBLIC KEY`. **Acha**, no cadastro e na busca de chaves.

### 3.7 Outras operações úteis

| O quê | Como |
|---|---|
| Copiar um valor (ex.: `blocks`) | botão direito no campo, nos detalhes → **Copy** → **Value** |
| Ver a conversa HTTP inteira | botão direito num pacote HTTP → **Follow** → **HTTP Stream** (não use para WebSocket: os quadros mascarados aparecem embaralhados) |
| Recomeçar a lista do zero | **Capture** → **Restart** (`Ctrl` + `R`) |
| Pausar | **Capture** → **Stop** (`Ctrl` + `E`) |
| Guardar para o plano B | **File** → **Save As…** → `ensaio.pcapng`; depois é só abrir o arquivo e mostrar os mesmos pacotes |

---

## 4. Mapa de usuários de teste

| | Alice (A) | Bruno (B) | Carla (C) |
|---|---|---|---|
| Usuário / senha | `alice` / `alice123` | `bruno` / `bruno123` | `carla` / `carla123` |
| Nome | Alice Andrade | Bruno Barros | Carla Castro |
| Papel | **admin** (cadastrar **primeiro**: [backend/api/auth.py:30-36](../../backend/api/auth.py#L30-L36)) | usuário | usuário |
| Processo / porta | terminal `alice` / **8080** | terminal `bruno` / **8081** | terminal `carla` / **8082** |
| URL | http://127.0.0.1:8080 | http://127.0.0.1:8081 | http://127.0.0.1:8082 |
| Keystore | `data\keystoreA\alice\` | `data\keystoreB\bruno\` | `data\keystoreC\carla\` |
| Navegador (só visual) | Chrome | Edge | Firefox |
| Nó inicial | Manaus | São Paulo | Brasília |
| Posição na tela | metade esquerda (`Win`+`←`) | metade direita (`Win`+`→`) | no grupo, 3 colunas com `Win`+`Z` |

Os nós seguem a ordem de cadastro ([backend/nos.py:25-27](../../backend/nos.py#L25-L27), [backend/nos.py:88-105](../../backend/nos.py#L88-L105)).
Alice (Manaus) e Bruno (São Paulo) **não** são vizinhos, então a mensagem A→B passa por **Brasília**. Desligando
Brasília, o caminho dá a volta por **Recife**.

O título da aba mostra a porta (`CriptoChat RSA :8080`). Confira antes de clicar.

**Telas do vídeo (1920×1080 sugerido):**
- Área de trabalho virtual 1 (alterne com `Win`+`Ctrl`+`←/→`): navegadores da Alice e do Bruno lado a lado.
- Área de trabalho virtual 2: VS Code à esquerda (60%) e Windows Terminal na aba `sql` à direita (40%).
- Wireshark: janela própria, maximizada quando for mostrar.

---

## 5. Cenários de teste

Cada cenário supõe que o anterior foi feito; o roteiro segue esta ordem. Todas as conversas são RSA 2048 (o diálogo
de nova conversa não oferece escolha de modo).

### Cenário 0: ambiente no ar

- **Pré-condições:** banco limpo; Wireshark capturando (seção 3.3); `backend`, `alice`, `bruno` e `carla` rodando.
- **Evidência:** `Invoke-RestMethod http://127.0.0.1:8000/api/health`; `sql "SELECT nome, ativo FROM servers"` → 4 nós.
- **Esperado:** as três URLs abrem na tela de login, sem "Contas com chaves neste aparelho".

### Cenário 1: cadastro e geração da chave

- **Pré-condições:** cenário 0; nenhum usuário.
- **Janelas:** navegador da Alice; depois VS Code, terminal `sql` e Wireshark.
- **Passos:** em :8080 → *Criar conta* → `alice` / `Alice Andrade` / `alice123` → *Gerar chaves e criar conta*.
  Repita em :8081 (`bruno`) e :8082 (`carla`).
- **Evidências:**
  - tela pós-cadastro: "Sua chave pública já está no servidor; a privada ficou aqui" e o cartão "publicada" com
    key_id, fingerprint e número de segurança ([frontend/pages/conta.py:183-192](../../frontend/pages/conta.py#L183-L192));
  - `sql "SELECT name, type FROM pragma_table_info('public_keys')"` → não há coluna de privada;
  - consulta das públicas (modo real) → 3 linhas, uma por usuário, PEM, status `ativa`;
  - `Get-ChildItem .\data\keystoreA\alice\*.pem` → um `.pem` começando com `BEGIN ENCRYPTED PRIVATE KEY`;
  - Wireshark, leitura A (seção 3.6): `POST /api/auth/register` com `public_key` e `prova`; busca C: `PRIVATE` não
    encontrado;
  - DevTools da Alice (`F12` → *Application* → *Local Storage* / *IndexedDB*) → nenhuma chave. Pode haver entradas
    internas do NiceGUI, mas nada com `BEGIN`.
- **Esperado:** Alice com selo `admin`; o menu da Alice tem *Observador* e o dos outros não.

### Cenário 2: A→B (1:1)

- **Pré-condições:** cenário 1; Alice e Bruno logados, lado a lado; Wireshark capturando.
- **Passos:** Alice → *Chat* → `+` → clicar em *Bruno Barros* → *Criar conversa* → enviar
  `Encontro as 15h na biblioteca`.
- **Evidências:**
  - Bruno recebe com o ícone verde de assinatura verificada; Alice vê ✓✓ (entregue);
  - Wireshark, leitura B (seção 3.6): quadro `send` com dois envelopes (para `bruno` e a cópia para `alice`) e
    `blocks` em base64; depois o quadro `message` só com o envelope do Bruno;
  - consulta dos envelopes → 2 linhas, mesmo `msg`, `para` e `to_key_id` diferentes;
  - `Select-String … -Pattern "biblioteca"` → nada;
  - Alice → ícone 🧪 do balão → *Inspetor*: passo 2 (RSA-OAEP: e = 65537, n de 2048 bits, até 190 bytes por bloco,
    tabela bloco → cifrado) e passo 3 (RSA-PSS, "O que é assinado"); Bruno → *Inspetor*: passos 5 a 7 (assinatura
    confere, decifragem, texto).
- **Esperado:** o texto só aparece nas telas da Alice e do Bruno.

### Cenário 3: A→B e C (grupo)

- **Pré-condições:** cenário 2; Carla logada (3 colunas com `Win`+`Z`).
- **Passos:** Alice → `+` → marcar Bruno e Carla → *Criar conversa* → enviar `Reuniao do grupo amanha`.
- **Evidências:**
  - consulta dos envelopes → **3 linhas** com o mesmo `msg` (bruno, carla e alice), com blocos diferentes;
  - Inspetor da Alice → seletor "Um envelope por destinatário. Ver o de:" (@bruno / @carla): os cifrados mudam;
  - Wireshark: um `send` com 3 envelopes (aparelho → servidor); depois dois `message` (servidor → cada destinatário).
- **Esperado:** os três leem. O mesmo texto gera cifrados diferentes, porque o OAEP é aleatório.

### Cenário 4: troca de chave (Bruno)

- **Pré-condições:** cenário 3 (Alice e Carla já buscaram a chave do Bruno).
- **Passos:** Bruno → *Minhas chaves* → cartão *Sua chave* → *Trocar chave*.
- **Evidências:**
  - no chat do grupo da Alice e da Carla: aviso "⚠ A chave de bruno mudou (real). Novo fingerprint…";
  - chaves do Bruno → a antiga `substituida` e a nova `ativa`; `key_events` → `substituida` e `criada`;
    `key_challenges` → 1 nonce com `usado = 1`;
  - Wireshark: filtro de troca (seção 3.5) → `POST /api/keys/challenge` (resposta com `nonce`) e `PUT /api/me/key`
    (`public_key`, `nonce`, `prova`); filtro de avisos → quadro `key_changed` para a Alice e a Carla;
  - `Get-ChildItem .\data\keystoreB\bruno\*.pem` → **dois** `.pem` (o antigo continua lá para ler o histórico);
  - Bruno → *Sair* → *Entrar* → as mensagens antigas do grupo continuam legíveis.
- **Esperado:** a Alice envia de novo no grupo e funciona (o cache foi invalidado e a nova chave foi buscada).

### Cenário 5: exclusão de chave (Carla, apagando a privada)

- **Pré-condições:** cenário 4.
- **Passos:** Carla → *Minhas chaves* → *Excluir chave* → senha `carla123` → **marcar** "Apagar também as chaves
  privadas deste aparelho" → *Excluir*.
- **Evidências:**
  - Alice e Bruno veem no grupo "⛔ carla excluiu a chave (real)…";
  - Alice tenta enviar no grupo → erro "sem chave ativa: carla";
  - chaves da Carla → `revogada`; `key_events` → `revogada`;
  - Wireshark: `POST /api/me/key/revoke` (leva `modo` e `senha`) e o quadro `key_revoked`;
  - `Get-ChildItem .\data\keystoreC\carla\*.pem` → nenhum `.pem`;
  - Carla → *Publicar nova chave* (mesmo cartão) → Alice vê "A chave de carla mudou"; a Alice envia e funciona;
  - Carla → *Sair* → *Entrar* → as mensagens antigas do grupo aparecem como **[mensagem descartada]**
    ("a chave privada desta mensagem não está neste aparelho").
- **Esperado:** o contraste com o cenário 4: trocar preserva o histórico; apagar a privada o perde para sempre.

### Cenário 6: demais funcionalidades

| Funcionalidade | Passos | Esperado |
|---|---|---|
| Caminho da mensagem | Alice → *Caminho da mensagem* | envelope animado Manaus › Brasília › São Paulo |
| Nó fora do ar | Alice → *Servidores* → desligar **Brasília** → enviar ao Bruno | caminho Manaus › Recife › São Paulo |
| Sem caminho (fila) | desligar também **Recife** → enviar ao Bruno → religar Brasília | relógio 🕒 "na fila: sem caminho…" → entrega sozinha ao religar |
| Fila offline | Bruno → *Sair* → Alice envia → Bruno → *Entrar* | Alice vê "aguardando bruno"; Bruno recebe ao entrar; Alice vê ✓✓ |
| Números de segurança | Chat → ícone 🛡 no cabeçalho da conversa | fingerprints iguais nos dois aparelhos |
| Diretório de chaves | *Minhas chaves* → *Consultar o diretório…* → `bruno,carla` | públicas e números de segurança |
| Adulteração | Alice → *Observador* → *Adulterar o próximo envelope* → enviar ao Bruno | Bruno: balão vermelho "rejeitada: AssinaturaInvalida…" |
| Experimentos do Inspetor | Inspetor do Bruno → *E se…?* | chave errada → o OAEP recusa todos os blocos; 1 bit trocado → a assinatura não confere |
| CRUD de clientes | Alice → *Clientes* → editar o Bruno (avatar 🐻) → mover a Carla de nó → remover a Carla → filtro *removidos* → *Reativar* | Alice e Bruno recebem o aviso de chave revogada da Carla |
| CRUD de nós | *Servidores* → *Novo nó* "Belém", ligado a Manaus | aparece na topologia |
| Observador | Alice → *Observador* | tráfego ao vivo, visão do servidor e visão do interceptador ("RSA-OAEP 2048 … inviável") |
| Laboratório | http://127.0.0.1:8080/laboratorio → *Exemplo clássico (n = 3233)* → *Quebrar*; depois alternar para **real** → usuário `bruno` → *Buscar a chave e quebrar* | 3233 = 53 × 61 em milissegundos; chave real "inviável" |

> No Laboratório, o seletor começa em **didático** ([frontend/pages/laboratorio.py:56](../../frontend/pages/laboratorio.py#L56)).
> **Mude para "real" antes de buscar o Bruno.** Se buscar em "didático", o Laboratório quebra a chave didática
> escondida do Bruno (seção 2.6.3), o que contradiz "só o modo real".
> Remover e reativar a Carla deixa ela **sem chave ativa** ([backend/api/clients.py:82](../../backend/api/clients.py#L82)).
> Faça isso **por último**.

---

## 6. Snapshots (para gravar por partes)

Se quiser gravar cena a cena, salve o estado depois de cada cenário, com **todos os processos parados** (`Ctrl+C`):

```powershell
Copy-Item -Recurse .\data .\snapshots\apos-cenario-3
```

Para restaurar (processos parados):

```powershell
Remove-Item -Recurse -Force .\data
Copy-Item -Recurse .\snapshots\apos-cenario-3 .\data
```

Depois suba tudo de novo (seção 2) e faça login nos três aparelhos: a sessão do aparelho fica só na memória do
processo. A pasta `snapshots\` não é ignorada pelo git; apague-a depois da gravação ou não faça commit dela.

---

## 7. Resetar o ambiente entre tomadas

1. `Ctrl+C` nos terminais `alice`, `bruno`, `carla` e `backend`.
2. Apague o banco e os keystores:

   ```powershell
   Remove-Item -Recurse -Force .\data, .\.nicegui -ErrorAction SilentlyContinue
   ```

3. No Wireshark: **Capture** → **Restart** (`Ctrl` + `R`) para limpar a lista.
4. Suba tudo de novo na ordem da seção 2.5.
5. Recarregue os navegadores (`Ctrl+F5`).

> **Sempre reinicie os front-ends depois de apagar o banco.** Um front-end antigo guarda o token e o cache de chaves
> na memória; com o banco novo, ele recebe 401 e mostra "sessão expirada".

---

## 8. Problemas comuns e soluções

| Sintoma | Causa | Solução |
|---|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | política de execução | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` no terminal |
| `[Errno 10048] … address already in use` / porta ocupada | processo antigo ainda rodando | `Get-NetTCPConnection -LocalPort 8000,8080,8081,8082 -State Listen \| Select-Object LocalPort, OwningProcess` e depois `Stop-Process -Id <PID>` |
| `No module named …` | venv não ativado nesse terminal | `.\.venv\Scripts\Activate.ps1` |
| Duas janelas mostram o mesmo usuário | as duas estão na mesma porta | cada usuário na sua porta (8080, 8081, 8082) |
| Ao entrar: "Este aparelho não tem as suas chaves privadas" | login na porta ou keystore errado (ex.: bruno na 8080) | sair e entrar na porta certa ([frontend/pages/conta.py:108-109](../../frontend/pages/conta.py#L108-L109)) |
| "Sem conexão com o servidor… tentando de novo" | back-end parado | subir o back-end; o aparelho reconecta sozinho |
| "sessão expirada" / 401 depois de um reset | front-end com o token do banco antigo | reiniciar o front-end e entrar de novo |
| Envio falha com "sem chave ativa: X" | X excluiu a chave ou foi removido e reativado | X → *Minhas chaves* → *Publicar nova chave* |
| Wireshark: a interface de loopback não aparece | Npcap sem loopback | seção 3.1 |
| Wireshark: nada aparece | captura na interface errada ou filtro de captura digitado errado | **Capture** → **Options** → confira a interface e o filtro `tcp port 8000` |
| Wireshark: aparece só "TCP", sem HTTP nem WebSocket | porta 8000 não decodificada como HTTP, ou a captura começou depois do login | seção 3.2a; depois **Sair** e **Entrar** no aparelho para reabrir o WebSocket |
| Wireshark: o conteúdo do WebSocket aparece como texto corrido | preferência de JSON não ativada | seção 3.2b (ou leia o texto corrido mesmo) |
| Wireshark: `frame contains "send"` não acha o quadro | quadros aparelho → servidor vão mascarados | use `websocket.opcode == 1 && tcp.dstport == 8000` (seção 3.5) |
| Wireshark: "Find" acha o texto da mensagem | a captura pegou as portas 8080–8082 (tela do aparelho) | refazer a captura com o filtro de captura `tcp port 8000` |
| No banco aparecem duas chaves por usuário / um `.json` no keystore | resíduo do modo didático | seção 2.6.3; use as consultas com `modo = 'real'` |
| Laboratório quebrou a chave do Bruno | o seletor estava em "didático" | mude para "real" antes de buscar |
| CORS | não se aplica: o navegador só fala com o NiceGUI, e o NiceGUI fala com o back-end de processo para processo | — |
| Cache do navegador / tela velha | página antiga do NiceGUI | `Ctrl+F5` |
| "Chave antiga no storage" | não há chave no navegador; ela está em `data\keystoreX` | o reset (seção 7) apaga os keystores |
| Arquivos travados ao apagar `data\` | OneDrive sincronizando ou processo ainda rodando | pausar o OneDrive (ícone na bandeja → *Pausar sincronização*) e parar os processos |
| Laboratório: *Medir* demora | gera primos de até 2048 bits em Python puro | clicar em *Medir* fora da câmera e só mostrar o resultado |

> **OneDrive:** o repositório está numa pasta do OneDrive, então `data\keystore*` (com as chaves privadas) é
> sincronizado com a nuvem. Para a gravação, pause a sincronização; para uso real, isso seria um vazamento.
