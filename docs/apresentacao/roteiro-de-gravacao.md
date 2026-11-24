# Roteiro de gravação: CriptoChat RSA

**Duração total: 24:00** (6 minutos de margem sobre o limite de 30). Pilar central: **confidencialidade**.
Toda a demonstração usa o **RSA 2048 bits com OAEP e PSS**, o único modo que as telas oferecem.

**Princípio do vídeo:** não abrimos o código. Cada cena mostra o sistema funcionando e você explica, enquanto mostra, o
que está acontecendo por baixo. As provas vêm do próprio sistema rodando:
- as **telas** do app (Inspetor, Minhas chaves, Observador, Laboratório);
- o **Wireshark** (o que passa na rede);
- o **banco** (o que o servidor guarda).

Se o professor pedir para ver o código, as referências `arquivo:linha` estão no [guia-de-estudo.md](guia-de-estudo.md).

Convenções:
- `[ação]` = o que você faz enquanto fala. Palavras em **negrito** na fala são para enfatizar.
- "Desktop 1" = navegadores (Alice à esquerda, Bruno à direita). "Desktop 2" = Windows Terminal (aba `sql`) à
  esquerda e Wireshark à direita. Para alternar: `Win`+`Ctrl`+`←/→`.
- Os comandos de banco usam a função `sql` de [ambiente-e-execucao.md §2.6](ambiente-e-execucao.md#26-terminal-sql-consultas-no-banco).
- O Wireshark já deve estar configurado conforme [ambiente-e-execucao.md §3](ambiente-e-execucao.md#3-wireshark-passo-a-passo)
  (porta 8000 decodificada como HTTP, WebSocket como JSON, zoom aumentado).
- Usuários: Alice `alice/alice123` (:8080, admin), Bruno `bruno/bruno123` (:8081), Carla `carla/carla123` (:8082).

Estado inicial:
- **banco limpo** e os 4 processos no ar;
- Wireshark **capturando desde antes do primeiro cadastro**, com o filtro de captura `tcp port 8000`;
- os 3 navegadores na tela de login;
- função `sql` carregada no terminal.

| # | Cena | Início | Duração |
|---|---|---|---|
| 1 | Abertura e objetivo | 00:00 | 1:00 |
| 2 | Arquitetura e ambiente rodando | 01:00 | 1:30 |
| 3 | Fundamentos do RSA | 02:30 | 1:30 |
| 4 | Geração e cadastro da chave | 04:00 | 3:00 |
| 5 | Envio A→B | 07:00 | 3:30 |
| 6 | Envio A→B e C (envelopes) | 10:30 | 2:00 |
| 7 | Troca e exclusão de chave | 12:30 | 3:30 |
| 8 | Demais funcionalidades | 16:00 | 3:30 |
| 9 | Prova de confidencialidade e Laboratório | 19:30 | 2:30 |
| 10 | Limitações e melhorias | 22:00 | 1:30 |
| 11 | Encerramento | 23:30 | 0:30 |
| | **Total** | | **24:00** |

---

## Cena 1: abertura e objetivo · 00:00 (1:00)

**Tela:** navegador da Alice em tela cheia, na tela de login (painel colorido à esquerda com "Mensagens que só quem
deve consegue ler").

**Navegação:**
1. Nenhuma ação até o fim da fala; no final, `Win`+`Ctrl`+`→` para o Desktop 2.

**Fala:**
> Olá! Este é o CriptoChat RSA, o nosso Trabalho 1 de Segurança da Informação. É um mensageiro com criptografia
> **ponta a ponta**: a mensagem é cifrada no aparelho de quem envia e só é decifrada no aparelho de quem recebe.
> O pilar que a gente quer garantir é a **confidencialidade**: nem o servidor, nem os nós da rede, nem alguém
> escutando o tráfego consegue ler o conteúdo. O algoritmo é o **RSA de 2048 bits**, com o padding **OAEP** para
> cifrar e **PSS** para assinar. Ao longo do vídeo eu vou mostrar cada fase da vida das chaves (criação,
> armazenamento, distribuição, uso, troca e exclusão), sempre com uma prova: na tela do app, na rede, com o Wireshark,
> e no banco do servidor.

**Evidência destacada:** o slogan e os três cartões "O par de chaves nasce aqui", "Só a pública vai ao servidor" e
"Cada mensagem sai cifrada e assinada".

**Transição:** "Primeiro, como o sistema está montado." → Desktop 2.

---

## Cena 2: arquitetura e ambiente rodando · 01:00 (1:30)

**Tela:** Windows Terminal com as abas `backend`, `alice`, `bruno` e `carla`; depois a documentação da API no
navegador; por fim o Wireshark.

**Navegação:**
1. Mostre a aba `backend` (linha `Uvicorn running on http://127.0.0.1:8000`).
2. Passe pelas abas `alice` (8080), `bruno` (8081) e `carla` (8082), 2 segundos cada.
3. Numa aba do navegador da Alice, abra http://127.0.0.1:8000/docs (a página Swagger da API). Role devagar pelos
   grupos: *autenticação*, *chaves*, *conversas*.
4. Alterne para o Wireshark (`Alt`+`Tab`). Mostre o nome da interface *Adapter for loopback traffic capture* na barra
   de título e, na barra de status embaixo, o contador de pacotes subindo.

**Fala:**
> São três partes. O **servidor**, na porta 8000, faz dois papéis: é o **diretório de chaves públicas** e o **relay**,
> que repassa as mensagens cifradas em tempo real; ele guarda tudo num banco SQLite. Cada um destes outros três
> processos é o **aparelho** de uma pessoa: a Alice na porta 8080, o Bruno na 8081 e a Carla na 8082. Cada aparelho
> tem a sua própria pasta de chaves, que é onde a chave privada mora.
> Um detalhe importante: o navegador é só a **tela** do aparelho. Quem gera as chaves, cifra e decifra é o processo
> do aparelho.
> `[Swagger]` Esta é a API do servidor. Repare que existe envio de chave **pública**, busca de chave **pública**,
> troca e revogação, mas não existe nenhuma operação que receba ou devolva chave privada.
> `[Wireshark]` E para provar o que passa na rede, o Wireshark está capturando desde já tudo o que os aparelhos e o
> servidor trocam pela porta 8000.

**Evidência destacada:** os 4 processos no ar; a lista de rotas da API, sem nenhuma rota de chave privada; a captura
ativa.

**Transição:** "Antes de usar, um minuto de matemática."

---

## Cena 3: fundamentos do RSA · 02:30 (1:30)

**Tela:** a tabela do exemplo numérico, usada como slide: a pré-visualização do [guia-de-estudo.md](guia-de-estudo.md)
na seção 2.3, ou a mesma tabela num slide ou numa imagem.

**Preparação:** deixe a tabela "Geração das chaves" da seção 2.3 aberta em tela cheia. Se usar o VS Code, abra o
arquivo e tecle `Ctrl`+`Shift`+`V` para ver só a pré-visualização formatada, não o código-fonte.

**Navegação:**
1. Mostre a tabela de geração (p = 61, q = 53, n = 3233, φ = 3120, e = 17, d = 2753).
2. Role até "Cifrar" e "Decifrar" (65 → 2790 → 65).

**Fala:**
> O RSA tem um par de chaves. A **pública** é o par (e, n) e serve para **cifrar**; a **privada** é o d e serve para
> **decifrar**. `[tabela]` Para gerar, sorteamos dois primos p e q, fazemos n = p vezes q, calculamos φ(n) =
> (p−1)(q−1), escolhemos um e e calculamos d, o inverso de e módulo φ. Com números pequenos: p = 61 e q = 53 dão
> n = 3233, e = 17 e d = 2753.
> `[cifrar/decifrar]` Cifrar é c = m elevado a e, mod n; decifrar é m = c elevado a d, mod n. A mensagem 65 vira 2790,
> e 2790 volta a ser 65. A segurança vem de que, sabendo só e e n, achar d exige **fatorar n**. Para 3233 é fácil; para
> o que usamos no app, um n de 2048 bits, é inviável.
> No app, além do tamanho, usamos **padding**: OAEP para cifrar e PSS para assinar. Ele mistura bytes aleatórios e
> uma estrutura conferível, então o mesmo texto nunca gera o mesmo cifrado, e uma chave errada ou um dado adulterado é
> detectado. O preço é o espaço: com 2048 bits cabem 190 bytes de mensagem por bloco, então uma mensagem maior vira
> vários blocos.

**Evidência destacada:** o exemplo numérico completo.

**Transição:** "Agora vamos ver isso acontecendo no cadastro." → Desktop 1.

---

## Cena 4: geração e cadastro da chave · 04:00 (3:00)

**Tela:** navegador da Alice em tela cheia → Wireshark → terminal `sql` → navegadores de novo.

**Navegação:**
1. Em :8080 → *Criar conta*. Digite `alice`, `Alice Andrade` e `alice123`.
2. Clique em *Gerar chaves e criar conta* e aguarde "Bem-vindo, Alice Andrade!" (1 a 2 segundos).
3. Aponte o cartão "publicada": key_id, fingerprint e número de segurança.
4. Clique em *Minhas chaves*. Aponte o mapa "Onde cada chave fica" (Este aparelho → Servidor) e, no cartão *Sua
   chave*, as duas metades: "Pública · no servidor" e "Privada · só aqui · d guardado cifrado com a sua senha".
5. **Wireshark: o que o cadastro enviou.**
   1. `Win`+`Ctrl`+`→` e clique no Wireshark. Na barra verde de filtro, digite
      `http.request.uri contains "/api/auth/register"` e tecle `Enter`. Sobra um pacote:
      `POST /api/auth/register HTTP/1.1 (application/json)`.
   2. Clique nesse pacote. No painel do meio, clique no ▶ de **JavaScript Object Notation: application/json**,
      depois no ▶ de **Object**, depois no ▶ de **Member: chaves** → **Array** → no primeiro **Object** cujo `modo`
      é `real`.
   3. Aponte os três membros: `modo`, `public_key` (`-----BEGIN PUBLIC KEY-----…`) e `prova`. **Não aponte** o
      membro `senha`, mais acima.
   4. Troque o filtro para `http || websocket` + `Enter`. Tecle `Ctrl`+`F`. Na barra que aparece, ajuste os seletores
      para **Packet details** / **Narrow & Wide** / **String**, digite `PRIVATE` e clique em **Find**. Aponte a
      barra de status: "No packet contains that string in its dissected display."
6. No terminal `sql`:
   ```powershell
   sql "SELECT name, type FROM pragma_table_info('public_keys')"
   sql "SELECT c.username, k.key_id, k.status, k.criada_em, substr(k.public_key,1,40) AS publica FROM public_keys k JOIN clients c ON c.id = k.client_id WHERE k.modo = 'real' ORDER BY k.id"
   Get-ChildItem .\data\keystoreA\alice\*.pem
   Get-ChildItem .\data\keystoreA\alice\*.pem | Get-Content -TotalCount 2
   ```
7. Desktop 1: cadastre rapidamente o **Bruno** (:8081, `bruno`, `Bruno Barros`, `bruno123`) e a **Carla**
   (:8082, `carla`, `Carla Castro`, `carla123`), sem comentar.

**Fala:**
> `[clicar Gerar chaves]` Ao clicar, o aparelho da Alice gerou um par RSA de 2048 bits, **aqui no aparelho**, nunca no
> servidor. A tela já mostra a chave pública publicada: o key_id, o fingerprint e o número de segurança.
> `[Minhas chaves]` Esta tela resume onde cada metade ficou: a pública foi para o servidor; a privada ficou só neste
> aparelho, guardada cifrada com a senha da Alice.
> `[Wireshark]` E o que foi para o servidor? Este é exatamente o pedido de cadastro que saiu do aparelho. Dentro de
> "chaves" vão três coisas: o modo, a chave **pública** e uma **prova**. A prova é uma assinatura feita com a privada:
> o servidor confere essa assinatura com a pública recebida e, se não bater, recusa o cadastro. Assim ninguém consegue
> publicar uma chave cuja privada não tem. `[Find PRIVATE]` E procurando a palavra "PRIVATE" em toda a captura…
> **nenhum pacote**. A privada nunca saiu do aparelho.
> `[sql pragma]` No banco do servidor, a tabela de chaves nem tem coluna para chave privada. `[sql publicas]` Aqui está
> a pública da Alice, em formato PEM, com status "ativa". `[Get-ChildItem]` E aqui, na pasta do aparelho da Alice, está
> a privada, num arquivo que começa com "ENCRYPTED PRIVATE KEY": cifrada com a senha.
> `[cadastrar Bruno e Carla]` Vou cadastrar também o Bruno e a Carla, cada um no seu aparelho. A Alice, por ter sido a
> primeira, é a administradora.

> **Nota para o apresentador (não precisa falar):** o objeto `chaves` do pacote tem **dois** itens; o segundo é o
> resíduo didático de 32 bits ([ambiente-e-execucao.md §2.6.3](ambiente-e-execucao.md#263-o-resíduo-do-modo-didático-para-não-ser-pego-de-surpresa)).
> Mostre só o `real`. Se preferir ser transparente, acrescente uma frase:
> "o cadastro ainda publica uma segunda chave, didática, de uma versão anterior; nenhuma tela a usa."

**Evidência destacada:** o cartão "publicada"; o par "Pública no servidor / Privada só aqui"; o JSON do cadastro no
Wireshark (só `modo`, `public_key` e `prova`); "No packet contains that string"; a ausência de coluna de privada;
`BEGIN ENCRYPTED PRIVATE KEY` no keystore.

**Transição:** "Com os três cadastrados, a Alice manda a primeira mensagem para o Bruno." → Desktop 1, com a Alice à
esquerda e o Bruno à direita.

---

## Cena 5: envio A→B · 07:00 (3:30)

**Tela:** Alice (esquerda) e Bruno (direita) no *Chat*; depois o Inspetor; depois Wireshark e terminal `sql`.

**Navegação:**
1. Alice → *Chat* → `+` → clique em *Bruno Barros* → *Criar conversa*.
2. Alice digita `Encontro as 15h na biblioteca` → `Enter`.
3. Aponte: o Bruno recebe com o ícone verde (passe o mouse: "assinatura de alice verificada"); a Alice vê ✓✓.
4. Alice: passe o mouse no balão → ícone 🧪 → Inspetor.
   - Aponte o cartão "quem vê o quê": *Você* lê o texto; *O servidor* sabe quem fala com quem; *Um espião na rede* só
     vê bytes embaralhados.
   - Abra o passo **1** (o texto vira bytes, junto com o remetente e o id).
   - Abra o passo **2** (RSA-OAEP com e = 65537, n de 2048 bits, até 190 bytes por bloco; a tabela bloco → cifrado).
   - Abra o passo **3** (RSA-PSS) e expanda "O que é assinado".
5. Bruno → *Inspetor* → a mensagem recebida → abra os passos **5** (✓ confere), **6** (decifrado com a privada do
   Bruno) e **7** (o remetente de dentro confere com o de fora).
6. **Wireshark: o quadro que a Alice enviou.**
   1. Desktop 2 → Wireshark. Filtro `websocket.opcode == 1 && tcp.dstport == 8000` + `Enter`. Ficam só os quadros de
      texto do aparelho para o servidor (Info: `WebSocket Text [FIN] [MASKED]`).
   2. Tecle `End`. Clique no último quadro **grande** (coluna *Length* acima de ~1000). Os pequenos são `ack`.
   3. Botão direito nele → **Show Packet in New Window**, e maximize essa janela.
   4. Expanda **WebSocket** e aponte `Mask: True`: o Wireshark desfaz a máscara do protocolo, que não é criptografia.
   5. Expanda **JavaScript Object Notation** → **Object**. Aponte `type: "send"`. Expanda **envelopes** →
      **Array**: há **dois Object**. Expanda o primeiro: `from: alice`, `to: bruno`, `to_key_id`, `mode: real`,
      `sent_at`, `blocks` (um texto base64 longo) e `signature`.
   6. Feche a janela. Troque o filtro para `websocket.opcode == 1 && tcp.srcport == 8000`, tecle `End` e clique no
      quadro `message` (o maior perto do fim). Expanda o JSON: só **um** envelope, `to: bruno`.
7. No terminal `sql`:
   ```powershell
   sql "SELECT e.id, substr(e.message_id,1,8) AS msg, c.username AS para, e.to_key_id, e.status, substr(e.conteudo,1,90) AS conteudo FROM envelopes e JOIN clients c ON c.id = e.recipient_id ORDER BY e.id DESC LIMIT 6"
   sql "SELECT name FROM pragma_table_info('messages')"
   Select-String -Path .\data\criptochat.db -Pattern "biblioteca" -SimpleMatch
   ```

**Fala:**
> `[criar conversa e enviar]` A Alice cria uma conversa com o Bruno e manda: "Encontro às 15h na biblioteca". Chegou,
> com o selo verde de assinatura verificada.
> `[Inspetor da Alice]` O Inspetor mostra, passo a passo, o que o aparelho da Alice fez. `[quem vê o quê]` Primeiro,
> o resumo: só a Alice e o Bruno leem; o servidor e um espião só veem bytes. `[passo 1]` O texto, junto com o nome do
> remetente e o id da mensagem, vira bytes. `[passo 2]` Esses bytes são cifrados com RSA-OAEP e a chave **pública do
> Bruno**, que o aparelho da Alice buscou no servidor. `[passo 3]` Depois, o envelope inteiro é assinado com a chave
> **privada da Alice**: aqui está exatamente o que foi assinado, todos os campos, inclusive os blocos cifrados.
> `[Inspetor do Bruno]` No aparelho do Bruno, o caminho inverso. Primeiro ele confere a assinatura com a pública da
> Alice; se um único bit tivesse mudado, a mensagem seria descartada antes de decifrar. Depois decifra com a privada
> **dele**, que só existe neste aparelho. E confere que o remetente escondido dentro da cifra é o mesmo do envelope,
> então ninguém consegue pegar o cifrado da Alice e reassinar como se fosse dele.
> `[Wireshark, quadro send]` Agora, a prova na rede. Este é o quadro que saiu do aparelho da Alice. O Wireshark tira a
> "máscara" do protocolo, que não é criptografia, e mostra o conteúdo: não há texto em lugar nenhum. Há **dois
> envelopes**, um para o Bruno e uma cópia para a própria Alice, cada um com os blocos cifrados e uma assinatura. Os
> metadados, de quem para quem, estão visíveis; o conteúdo, não. `[quadro message]` E este é o que o servidor entregou
> ao Bruno: só o envelope dele.
> `[sql envelopes]` No banco, o servidor guardou exatamente esses dois envelopes, um por destinatário, com o
> identificador da chave que pode abrir cada um. `[sql messages]` A tabela de mensagens só tem cabeçalho: id,
> conversa, remetente e horário, sem nenhuma coluna de texto. `[Select-String]` E procurando "biblioteca" no arquivo
> do banco… **nada**. O servidor só confere quem envia e para quem, e guarda o envelope como chegou; ele não decifra.

**Evidência destacada:** o cartão "quem vê o quê"; os passos 2 e 3 do Inspetor; o quadro `send` sem texto e com dois
envelopes; o quadro `message` com um só; 2 linhas em `envelopes`; `messages` sem texto; `Select-String` vazio.

**Transição:** "E se forem várias pessoas?" → `Win`+`Z` com três colunas (Alice, Bruno e Carla).

---

## Cena 6: envio A→B e C (envelopes) · 10:30 (2:00)

**Tela:** Alice, Bruno e Carla em três colunas; depois o Inspetor da Alice; depois `sql` e Wireshark.

**Navegação:**
1. Alice → `+` → marque *Bruno Barros* e *Carla Castro* → *Criar conversa*.
2. A Alice envia `Reuniao do grupo amanha`. Bruno e Carla recebem com o ícone verde.
3. Alice → 🧪 na mensagem do grupo → Inspetor → seletor "Um envelope por destinatário. Ver o de:" → alterne entre
   **@bruno** e **@carla** com o passo 2 aberto.
4. No terminal `sql`: repita a consulta de envelopes (3 linhas novas com o mesmo `msg`).
5. Wireshark: filtro `websocket.opcode == 1 && tcp.dstport == 8000` → `End` → o último quadro grande → expanda
   **JSON** → **envelopes** → **Array**: agora há **três Object** (`to: bruno`, `to: carla`, `to: alice`). Expanda
   dois deles e compare o começo de `blocks`.

**Fala:**
> `[criar grupo e enviar]` Agora um grupo com a Alice, o Bruno e a Carla.
> `[Inspetor, alternar]` O Inspetor mostra que a mensagem não foi cifrada uma vez só: há **um envelope por
> destinatário**. O do Bruno foi cifrado com a pública do Bruno; o da Carla, com a pública da Carla. Mesmo com o mesmo
> texto, os cifrados são completamente diferentes, porque o OAEP mistura bytes aleatórios a cada cifragem. A Carla não
> consegue abrir o envelope do Bruno, e vice-versa. E a Alice recebe a própria cópia, cifrada com a pública dela, que é
> como ela relê o histórico.
> `[sql]` No banco, a mesma mensagem gerou **três envelopes**. `[Wireshark]` E na rede foi um único envio com os três.
> O servidor exige exatamente um envelope por participante: se faltar alguém, ou sobrar, ele recusa.

**Evidência destacada:** o seletor de destinatário do Inspetor com cifrados diferentes; 3 envelopes com o mesmo
`message_id`; o array com 3 envelopes no Wireshark.

**Transição:** "E quando uma chave muda?" → o Bruno em destaque (direita) e a Alice à esquerda.

---

## Cena 7: troca e exclusão de chave · 12:30 (3:30)

**Tela:** Bruno → *Minhas chaves*; Alice e Carla no chat do grupo; `sql`; Wireshark.

**Navegação, troca (Bruno):**
1. Bruno → *Minhas chaves*. Aponte o cartão *Sua chave* e a linha *Ciclo de vida* (uma chave, "ativa").
2. Clique em *Trocar chave*. Aguarde "Nova chave … publicada; os contatos foram avisados". O *Ciclo de vida* passa a
   mostrar "substituída → ativa", as duas com "privada neste aparelho".
3. Alice (e Carla) → chat do grupo: o aviso "⚠ A chave de bruno mudou (real)…".
4. No terminal `sql`:
   ```powershell
   sql "SELECT k.key_id, k.status, k.criada_em, k.substituida_em FROM public_keys k JOIN clients c ON c.id = k.client_id WHERE c.username = 'bruno' AND k.modo = 'real'"
   sql "SELECT nonce, client_id, usado, expira_em FROM key_challenges"
   Get-ChildItem .\data\keystoreB\bruno\*.pem
   ```
5. Wireshark: filtro `http.request.uri contains "/api/keys/challenge" || http.request.uri contains "/api/me/key"` +
   `Enter`. Aparecem `POST /api/keys/challenge` e `PUT /api/me/key`. Clique no `PUT` → **JSON** → **Object**: aponte
   `nonce`, `public_key` e `prova`. Depois, filtro `frame contains "key_changed"` → clique num quadro → **JSON**:
   `type: key_changed`, `user: bruno`, `fingerprint`.
6. Bruno → *Sair* → entre com `bruno`/`bruno123` → *Chat* → grupo: as mensagens antigas continuam legíveis.

**Navegação, exclusão (Carla, apagando a privada):**
7. Carla → *Minhas chaves* → *Excluir chave* → senha `carla123` → **marque** "Apagar também as chaves privadas…" →
   *Excluir*. O cartão mostra "sem chave ativa".
8. Alice → grupo: o aviso "⛔ carla excluiu a chave (real)…". A Alice envia `teste` → notificação vermelha
   "keys: sem chave ativa: carla".
9. No `sql`, a consulta de chaves trocando `bruno` por `carla` (status `revogada`) e
   `Get-ChildItem .\data\keystoreC\carla\*.pem` (não sobra nenhum).
10. Wireshark: filtro `frame contains "key_revoked"` → o aviso enviado à Alice e ao Bruno.
11. Carla → *Publicar nova chave*. A Alice vê "A chave de carla mudou". A Alice envia `de volta` e funciona.
12. Carla → *Sair* → *Entrar* → grupo: as mensagens antigas aparecem como **[mensagem descartada]**.

**Fala:**
> `[Minhas chaves]` O Bruno vai trocar a chave. `[Trocar chave]` Nesse clique, o aparelho dele gerou um par novo, pediu
> ao servidor um **desafio** (um número aleatório que vale 60 segundos e uma vez só) e assinou esse desafio com a
> **nova** privada. O servidor confere a assinatura, marca a chave antiga como "substituída", publica a nova e avisa
> todos os contatos do Bruno.
> `[aviso na Alice]` E aqui está o aviso na Alice: "a chave de bruno mudou", com o novo fingerprint.
> `[sql]` No banco: a antiga está "substituida", a nova "ativa", e o desafio está marcado como usado: não dá para
> reaproveitá-lo. `[Wireshark]` Na rede, o pedido de troca levou o desafio, a nova pública e a prova, e o servidor
> mandou o aviso `key_changed` aos contatos. `[keystore]` No aparelho do Bruno ficaram **as duas** privadas.
> `[sair/entrar]` Por isso, quando o Bruno sai e entra de novo, o histórico antigo, cifrado para a chave velha,
> continua legível. Trocar a chave não destrói o passado.
> `[Excluir]` Agora o caso extremo: a Carla **exclui** a chave e marca para apagar também a privada deste aparelho. O
> servidor pede a senha de novo, porque um token roubado não basta. `[aviso e erro]` A Alice foi avisada, e se tenta
> mandar no grupo, o envio é bloqueado: não existe mais chave pública ativa para cifrar para a Carla. `[sql e pasta]` No
> servidor a chave ficou "revogada"; no aparelho, o arquivo da privada foi apagado.
> `[Publicar nova]` A Carla publica uma chave nova, a Alice recebe o alerta e o grupo volta a funcionar.
> `[sair/entrar Carla]` Mas olhem o histórico da Carla: as mensagens antigas estão **descartadas**. Elas continuam no
> servidor, cifradas, mas a única chave que as abria não existe mais. Essa é a diferença entre trocar e apagar.

**Evidência destacada:** o *Ciclo de vida* "substituída → ativa"; os avisos de troca e exclusão no chat; os status
`substituida` e `revogada` no banco; o desafio com `usado = 1`; o `PUT /api/me/key` e os quadros
`key_changed`/`key_revoked` no Wireshark; dois `.pem` no Bruno e nenhum na Carla; "[mensagem descartada]".

**Transição:** "Agora o resto do sistema, rapidamente." → a Alice em tela cheia.

---

## Cena 8: demais funcionalidades · 16:00 (3:30)

**Tela:** navegador da Alice (admin), com o Bruno à direita quando indicado.

**Navegação (cerca de 25 segundos por item):**
1. **Caminho**: Alice → *Caminho da mensagem* → mensagem "Encontro as 15h…": Manaus › Brasília › São Paulo.
2. **Nó fora do ar**: *Servidores* → desligue **Brasília** (switch) → *Chat* → conversa com o Bruno → envie `desvio`
   → *Caminho*: Manaus › Recife › São Paulo.
3. **Sem caminho**: *Servidores* → desligue **Recife** → envie `fila` ao Bruno → relógio 🕒 "na fila: sem caminho…"
   → religue **Brasília** → a mensagem é entregue sozinha (✓✓). Religue também **Recife**.
4. **Fila offline**: Bruno → *Sair*. A Alice envia `voce esta offline` → "aguardando bruno". Bruno → *Entrar* → recebe;
   a Alice vê ✓✓.
5. **Números de segurança**: Alice → no chat com o Bruno, ícone 🛡 do cabeçalho; Bruno → o mesmo ícone: os números de
   @bruno coincidem.
6. **Adulteração**: Alice → *Observador* → *Adulterar o próximo envelope* → *Chat* → envie `adulterada` ao Bruno →
   o Bruno vê um balão vermelho "rejeitada: AssinaturaInvalida…".
7. **Experimentos**: Bruno → Inspetor da mensagem "Encontro…" → *E se…?* → *…alguém tentar decifrar com outra
   chave?* (o OAEP recusa cada bloco) e *…um bit mudar no caminho?* (a assinatura não confere).
8. **CRUD de clientes**: Alice → *Clientes* → editar o Bruno (avatar `🐻`) → *Salvar*; remover a Carla → filtro
   *removidos* → *Reativar*.
9. **CRUD de nós**: *Servidores* → *Novo nó* → nome `Belém`, região `Norte`, ligado a `Manaus` → *Salvar*.

**Fala:**
> `[Caminho]` Cada cliente fica num nó de retransmissão. A mensagem da Alice, em Manaus, até o Bruno, em São Paulo,
> passou por Brasília, e em cada nó ela continua **cifrada**.
> `[desligar Brasília]` Se Brasília cai, o caminho é recalculado e dá a volta por Recife.
> `[desligar Recife]` Sem nenhum caminho, a mensagem fica na fila (o relógio) e é entregue sozinha quando um nó volta.
> `[offline]` O mesmo vale para quem está offline: o envelope cifrado espera no servidor e é entregue quando o Bruno
> entra; a Alice recebe a confirmação.
> `[números de segurança]` Estes números de segurança são derivados do fingerprint da chave. Comparando pessoalmente
> com o do Bruno, a Alice confirma que a chave que o servidor entregou é mesmo a dele.
> `[adulteração]` Agora o servidor age de má-fé: altera um único bit do próximo envelope. O Bruno **rejeita** a
> mensagem, porque a assinatura cobre todos os blocos. `[experimentos]` E no Inspetor: tentar decifrar com outra chave
> privada não devolve nem lixo, porque o OAEP percebe e recusa. Trocar um bit muda todo o hash, e a assinatura deixa
> de conferir.
> `[Clientes]` Por fim, os cadastros: editar perfil, mudar de nó, remover (o que revoga as chaves e avisa os
> contatos) e reativar. `[Servidores]` E o cadastro de nós, com as ligações entre eles.

**Evidência destacada:** o caminho recalculado; 🕒 → ✓✓; a rejeição pela assinatura; a recusa do OAEP; os avisos de
revogação ao remover a Carla.

**Transição:** "Para fechar a prova: o que o servidor vê e o que o usuário vê." → Alice → *Observador*.

---

## Cena 9: prova de confidencialidade e Laboratório · 19:30 (2:30)

**Tela:** Alice → *Observador*; depois `/laboratorio`.

**Preparação fora da câmera:** antes da cena, abra http://127.0.0.1:8080/laboratorio numa aba separada e clique em
*Medir* e *Medir fatoração*. Levam alguns segundos, e o resultado some se a página for recarregada. Deixe a aba pronta.

**Navegação:**
1. *Observador* → desligue "acompanhar o mais recente" → na lista *Tráfego ao vivo*, clique num envelope
   `@alice → @bruno`.
2. Mostre o cartão *Visão do servidor*: quem → quem, quando, por onde, tamanho, blocos em hexadecimal e "O texto não
   está aqui".
3. Mostre o cartão *Visão do interceptador*: o quadro capturado, a tentativa de ler o 1º bloco como texto (lixo) e
   "RSA-OAEP 2048: … inviável".
4. Aba `/laboratorio` → *Exemplo clássico (n = 3233)* → *Quebrar*: aparecem os passos 1 a 4.
5. No seletor ao lado do campo de usuário, clique em **real** (ele começa em "didático") → usuário `bruno` →
   *Buscar a chave e quebrar*: "n com 2048 bits (617 dígitos)… inviável".
6. Role até os dois gráficos já medidos e a extrapolação ("2048 bits ≈ 10^… anos").

**Fala:**
> `[Visão do servidor]` Este é o painel do administrador, com tudo o que o servidor sabe de um envelope: quem falou com
> quem, quando, por onde passou e quantos bytes. E o conteúdo: só blocos cifrados. O servidor não tem a privada de
> ninguém, então **não tem como ler**; ele só repassa e registra esses metadados.
> `[Visão do interceptador]` Um espião na rede vê o mesmo quadro que nós vimos no Wireshark; tentando ler os bytes como
> texto, só sai lixo. Para ler, precisaria da privada do Bruno.
> `[Laboratório, 3233]` E por que 2048 bits? Com a chave pequena do exemplo, o atacante fatora n na hora: 3233 é 53
> vezes 61, daí sai φ, daí sai d, e ele lê tudo. `[real]` Com a chave real do Bruno, o mesmo ataque exigiria fatorar um
> número de 617 dígitos. `[gráficos]` Os gráficos mostram o tempo de fatoração dobrando a cada 4 bits; extrapolado para
> 2048 bits, fica astronomicamente fora de alcance. A confidencialidade depende do **tamanho da chave** e do **padding**.

**Evidência destacada:** "O texto não está aqui: o servidor não tem a privada de ninguém"; "RSA-OAEP 2048 …
inviável"; a quebra de 3233 contra a chave real inviável; a extrapolação dos gráficos.

**Transição:** "Isso não quer dizer que o sistema não tenha limites."

---

## Cena 10: limitações e melhorias · 22:00 (1:30)

**Tela:** Wireshark no `POST /api/auth/login`; depois o diálogo de números de segurança da Alice.

**Navegação:**
1. Wireshark → filtro `http.request.uri contains "/api/auth/login"` + `Enter` → clique no pacote → **JSON** →
   **Object** → aponte o membro `senha`, em claro.
2. Desktop 1 → Alice → *Chat* → conversa com o Bruno → ícone 🛡 (números de segurança).

**Fala:**
> Algumas limitações que nós conhecemos. Primeiro, **não há TLS**: a comunicação é `http` e `ws` puros. O conteúdo das
> mensagens continua cifrado, mas metadados, o token e até a senha do login trafegam em claro, como dá para ver aqui no
> Wireshark. E essa senha é a mesma que protege a chave privada no aparelho. Em produção, HTTPS e WSS seriam
> obrigatórios.
> `[números de segurança]` Segundo, a **autenticidade das chaves públicas**: o servidor é o diretório. Se ele for
> malicioso no primeiro contato, pode entregar uma chave falsa, num ataque man-in-the-middle. O aparelho memoriza o
> fingerprint e avisa quando ele muda, e há estes números de segurança para comparar pessoalmente, mas o aviso não
> bloqueia o envio.
> Terceiro, usamos **RSA puro**, por blocos. O padrão da indústria é a criptografia **híbrida**: uma chave AES
> aleatória cifra a mensagem e o RSA cifra só essa chave, sem limite de tamanho e bem mais rápido.
> Quarto, não há **sigilo futuro**: se uma privada vazar um dia, todo o histórico daquela chave guardado no servidor
> pode ser lido.

> **[Opcional, se quiser mencionar o resíduo]** "E uma limpeza pendente: o cadastro ainda gera uma chave didática de
> 32 bits de uma versão anterior. Nenhuma tela a usa, mas o ideal é parar de gerá-la."

**Evidência destacada:** a senha em claro no Wireshark; os números de segurança como defesa manual contra MITM.

**Transição:** volte para a tela *Início* da Alice (Desktop 1).

---

## Cena 11: encerramento · 23:30 (0:30)

**Tela:** *Início* da Alice (contadores e o roteiro da demonstração).

**Fala:**
> Resumindo: a chave nasce no aparelho, só a metade pública vai ao servidor, cada mensagem é cifrada com a pública de
> cada destinatário e assinada pelo remetente, e o servidor só guarda e repassa o que não consegue ler. Trocar a chave
> preserva o histórico; excluir e apagar a privada o torna ilegível para sempre. Obrigado!

---

## Checklist pré-gravação

**Ambiente**
- [ ] OneDrive com a sincronização **pausada**.
- [ ] Banco limpo (`Remove-Item -Recurse -Force .\data, .\.nicegui`).
- [ ] `python -m pytest -q` passando.
- [ ] Terminais `backend` (8000), `alice` (8080), `bruno` (8081) e `carla` (8082) no ar, com o venv ativado.
- [ ] Terminal `sql` com a função `sql` carregada (teste uma consulta).
- [ ] Os três navegadores na tela de login, cada um na sua porta (confira `:8080`, `:8081` e `:8082` no título da aba).
- [ ] Tabela do exemplo numérico (guia §2.3) pronta para a cena 3, em pré-visualização ou num slide.
- [ ] Laboratório: aba pronta para clicar em *Medir* e *Medir fatoração* fora da câmera, antes da cena 9.

**Wireshark**
- [ ] Interface *Adapter for loopback traffic capture* disponível (ambiente §3.1).
- [ ] *Decode As* da porta 8000 como HTTP salvo; WebSocket como JSON (ambiente §3.2).
- [ ] Captura iniciada com o filtro de captura `tcp port 8000` **antes do primeiro cadastro** (ambiente §3.3).
- [ ] Zoom aumentado (`Ctrl` + `+`) e o painel *Packet Bytes* oculto.
- [ ] Ensaio feito e salvo em `ensaio.pcapng` (plano B).

**Tela**
- [ ] Resolução 1920×1080; escala do Windows entre 100% e 125%.
- [ ] Zoom dos navegadores entre 110% e 125% (`Ctrl` + `+`).
- [ ] Terminal com fonte 16 ou maior.
- [ ] Desktop 1 = navegadores; Desktop 2 = terminal `sql` e Wireshark. Nenhum editor de código aberto.

**Distrações**
- [ ] Notificações desligadas (Windows: *Não perturbe*; feche Discord, WhatsApp, Teams e e-mail).
- [ ] Abas desnecessárias fechadas; favoritos ocultos (`Ctrl`+`Shift`+`B`).
- [ ] Nenhuma senha real em lugar nenhum (as de demonstração aparecem no Wireshark).
- [ ] Microfone testado; roteiro aberto num segundo monitor ou impresso.

## Plano B

| Falha durante a gravação | O que fazer |
|---|---|
| Um aparelho trava ou a tela não atualiza | `Ctrl+F5` no navegador; se persistir, `Ctrl+C` no terminal e suba de novo (refaça o login; a chave está no keystore) |
| O back-end cai | Suba de novo; os aparelhos reconectam sozinhos (o indicador do cabeçalho volta a "conectado") |
| Porta ocupada ao subir | Veja [ambiente-e-execucao.md §8](ambiente-e-execucao.md#8-problemas-comuns-e-soluções) |
| Wireshark mostra só "TCP" | *Decode As* (ambiente §3.2a); depois **Sair** e **Entrar** no aparelho para reabrir o WebSocket |
| Wireshark não mostra o quadro | Abra o `ensaio.pcapng` gravado no ensaio (**File** → **Open**) e mostre os mesmos pacotes; ou mostre o *Observador > Visão do interceptador*, que é o quadro capturado |
| Erro inesperado num cenário | Pare a gravação, restaure o snapshot do cenário anterior ([ambiente-e-execucao.md §6](ambiente-e-execucao.md#6-snapshots-para-gravar-por-partes)) e regrave só aquela cena |
| Estourou o tempo | Corte nesta ordem: CRUD de nós (8.9) → experimentos (8.7) → números de segurança (8.5) → gráficos do Laboratório (9.6) |
| "sem chave ativa" inesperado | O usuário perdeu a chave ativa (remoção, reativação ou exclusão): *Minhas chaves* → *Publicar nova chave* |
| O professor pede para ver o código | As referências `arquivo:linha` de cada passo estão no [guia-de-estudo.md](guia-de-estudo.md), seção 4 |
| Gravar por partes | Salve um snapshot ao fim das cenas 4, 6 e 7; cada cena começa de um estado conhecido. Reinicie a captura do Wireshark antes do login de cada parte |
