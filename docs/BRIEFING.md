# BRIEFING: system-one-lab

> Salve este arquivo em `docs/BRIEFING.md` na raiz do repositório.
> Primeira mensagem no Claude Code: *"Leia docs/BRIEFING.md por inteiro, me diga o que
> entendeu em 10 linhas e comece pela Tarefa 1. Não avance para a Tarefa 2 sem eu aprovar."*

---

## 1. O que é este projeto

Repositório público em `github.com/victorbvieira/system-one-lab`, mantido por Victor
Vieira (BIDU Gestão e Participações). Serve de base para artigos técnicos.

**Pergunta que o repositório responde:** para decisões tipadas, um modelo System One
dedicado (TypeSafe Jev) entrega a mesma qualidade que um LLM de fronteira, e por quanto
menos? E onde ele falha?

Um modelo System One não escreve texto. Recebe um estado (o material a julgar) e perguntas
tipadas, e devolve cada resposta com uma confiança e a distribuição de probabilidades.

**Não é** uma comparação definitiva entre modelos. Datasets pequenos, domínio único,
rotulagem de uma pessoa. Isso precisa estar escrito no README e em todo artigo.

## 2. Estado atual do repositório

Um commit, com:

- `LICENSE` (Apache 2.0)
- `README.md` contendo apenas a linha de descrição

Falta tudo o mais. Não existe código, `.gitignore`, `pyproject.toml` nem estrutura.

## 3. Decisões já tomadas (não reabrir sem motivo)

| Item | Decisão |
|---|---|
| Linguagem | Python 3.12+, gerenciado com `uv` |
| Agentes | Pydantic AI (`pydantic-ai-slim[typesafe]`) |
| Avaliação | Pydantic Evals |
| Modelo System One | `typesafe:jev-1.13.0`, versão fixada, nunca `jev-latest` em resultado publicado |
| Baselines | via OpenRouter |
| Observabilidade | Langfuse self-hosted, opcional, nunca obrigatório para rodar |
| Licença de código | Apache 2.0 |
| Licença de conteúdo | CC BY 4.0, em `LICENSE-CONTENT` |
| Idioma | código e docstrings em inglês, README e artigos em português, dados em português |

Fixar a versão do modelo importa: os aliases movem quando a TypeSafe publica uma versão
nova, e um limiar calibrado contra uma versão deixa de valer na seguinte.

## 4. Estrutura alvo

```
system-one-lab/
  pyproject.toml
  README.md
  LICENSE                     Apache 2.0 (já existe)
  LICENSE-CONTENT             CC BY 4.0
  .gitignore
  .env.example                TYPESAFE_API_KEY, OPENROUTER_API_KEY, LANGFUSE_*
  docs/
    BRIEFING.md               este arquivo
    metodologia.md            como os datasets foram feitos e por que confiar neles
    anonimizacao.md           o pipeline de PII, detalhado
  lab/
    __init__.py
    modelos.py                registro de modelos e preços fixados
    custo.py                  cálculo de custo a partir de usage + preços
    metricas.py               increment_eval_metric, avaliadores custom
    permutacao.py             teste de estabilidade à ordem das opções
    relatorio.py              impressão, baseline e export JSON
    run.py                    CLI: --caso, --modelo, --comparar, --repeticoes
  casos/
    canal-de-denuncia/
      tipos.py                output_type e rubrica de urgência
      gramatica/              templates, slots e regras de rótulo
      gerar.py                gera o dataset sem LLM
      dataset.yaml            gerado, versionado
      holdout.yaml            escrito e revisado à mão, versionado
      agente.py
    selecao-de-pauta/
      ...                     mesmo formato, depois
  anonimizador/
    __init__.py
    padroes.py                regex + dígito verificador (CPF, CNPJ, telefone, e-mail, CEP, placa)
    nomes.py                  NER + gazetteer + pseudônimo determinístico
    canarios.py               PII plantada para medir recall em CI
  precos/
    openrouter-2026-09-20.json
  resultados/
    <caso>/<modelo>/<execucao>.json
    history.jsonl
  artigos/
```

## 5. Caso 1: grau de urgência de uma denúncia

### 5.1 A escala

Rubrica ordinal de quatro níveis, declarada como `IntEnum` com docstring em cada membro,
porque é assim que o Jev entende rubrica (cada nível precisa de uma descrição, senão é erro
antes de sair a requisição):

- `0` rotina: apurar no fluxo normal, sem prazo especial
- `1` relevante: apurar dentro da semana
- `2` grave: apurar em 24 horas, envolve continuidade, hierarquia ou vários afetados
- `3` crítico: risco físico, retaliação em curso ou ilícito em andamento, resposta imediata

### 5.2 A regra de ouro do desenho

Não perguntar "qual a urgência?" em um campo só. O Jev responde pior quando uma pergunta
pesa várias coisas ao mesmo tempo: não dá erro, devolve um número plausível com confiança
baixa, e você descobre tarde. Então pergunte os **sinais** separados, um por campo, e
componha a urgência em Python:

- `risco_fisico_iminente` (bool)
- `em_andamento` (bool, o fato continua acontecendo)
- `retaliacao` (bool, há ameaça ou punição contra quem relata)
- `hierarquia_do_acusado` (escolha: par, gestor direto, alta liderança, externo)
- `afetados` (escolha: uma pessoa, um time, a empresa toda, indeterminado)
- `tem_evidencia` (bool, o relato cita anexo, testemunha ou registro)

A urgência final sai de uma função determinística sobre esses campos. Isso dá três ganhos:
o rótulo vira auditável, a rubrica fica discutível com o jurídico, e quando o modelo erra
você sabe **qual sinal** ele errou.

Guardar também o campo composto pedido diretamente ao modelo, para comparar as duas
abordagens no artigo. É um achado publicável por si só.

### 5.3 Limiares assimétricos

Um falso negativo em nível 3 custa muito mais que um falso positivo. Então
`typesafe_boolean_threshold` desce para os campos de risco (um `True` só precisa ser
plausível) e a métrica principal do caso é **recall de nível 3**, não acurácia média.

## 6. Como gerar o dataset sem LLM

Esta é a parte central e é inegociável: **nenhum LLM escreve os dados deste repositório.**
Três motivos. Dado gerado por LLM carrega o viés do LLM que vai ser avaliado, o que
contamina o benchmark. Torna o dataset irreprodutível. E levanta dúvida sobre proveniência
em um repo público que fala de canal de denúncia.

### 6.1 Gramática combinatória

Um gerador determinístico, com semente fixa, que combina:

1. **Cenário**: assédio moral, assédio sexual, fraude financeira, desvio de material,
   segurança do trabalho, discriminação, conflito de interesse, retaliação, uso indevido
   de dados, irregularidade ambiental.
2. **Flags de gravidade**: as seis do item 5.2, ligadas e desligadas de forma combinatória.
   O rótulo sai das flags, não do texto. Rótulo nunca é opinião de ninguém.
3. **Registro linguístico**: formal, coloquial, telegráfico, com erro de digitação, com
   mistura de maiúsculas, com gíria regional, muito curto, muito longo e prolixo.
4. **Slots preenchidos**: nomes, cargos, setores, datas, valores e locais, vindos do Faker
   com locale `pt_BR` e semente fixa.

Com 10 cenários × combinações de flags × 8 registros já passa de mil casos rotulados, todos
reproduzíveis a partir da semente.

### 6.2 Ruído obrigatório

Sem isso o benchmark vira detector de palavra-chave e o resultado não vale nada:

- **Negações**: "não houve ameaça nenhuma, mas quero registrar" em caso de nível baixo.
- **Distratores lexicais**: palavras alarmantes (arma, sangue, polícia) em contexto benigno,
  tipo "o cara é tiro" falando de um colega produtivo.
- **Eufemismo**: nível 3 escrito de forma contida, sem nenhuma palavra alarmante, que é
  como a maioria das denúncias graves realmente chega.
- **Relato ambíguo**: casos onde a flag correta é indeterminada. O rótulo desses é
  "indeterminado" e eles entram na métrica de abstenção, não na de acurácia.

### 6.3 Holdout humano

O dataset sintético mede se a abordagem funciona. Ele **não** prova que funciona no mundo.
Por isso, um `holdout.yaml` com 60 casos escritos e rotulados à mão por Victor e pelo
Henrique, sem usar a gramática. A métrica que vai no artigo é a do holdout; a do sintético
serve para iterar rápido.

Se a acurácia no sintético for muito maior que no holdout, a gramática vazou o rótulo.
Isso é um resultado, não um fracasso, e vale parágrafo no artigo.

## 7. Anonimização sem LLM

Duas coisas diferentes, não confundir:

- O dataset do repo é **sintético**, então não tem PII real para anonimizar.
- O anonimizador existe para o pipeline que um dia vai ler relato real, e para ser testado
  contra a PII sintética que a gramática planta de propósito.

### 7.1 Camada 1: determinística (regex + validação)

Pega o que tem formato: CPF e CNPJ com verificação de dígito verificador, telefone
brasileiro (fixo e celular, com e sem DDD, com e sem +55), e-mail, CEP, placa Mercosul e
antiga, chave PIX aleatória, RG, matrícula, cartão com Luhn, IP, URL.

Validar o dígito verificador em vez de só casar o padrão derruba o falso positivo, que é o
que mais atrapalha: um número de processo não vira CPF.

Cobertura alta, zero dependência, zero custo, cem por cento reprodutível.

### 7.2 Camada 2: nomes próprios

Ordem de preferência:

1. **Gazetteer**, que é o mais previsível: lista estática de prenomes e sobrenomes
   brasileiros comuns (a lista de nomes do censo do IBGE serve), casada com limite de
   palavra e sensível a maiúscula. Rápido, auditável, funciona offline.
2. **NER estatístico**: spaCy com `pt_core_news_lg`, entidade `PER` e também `ORG` e `LOC`
   quando quiser esconder a empresa. Pega o nome que não está na lista.
3. **Microsoft Presidio** (MIT) por cima das duas, se quiser orquestração pronta com
   reconhecedores customizados e um anonimizador configurável. Ele aceita reconhecedor
   próprio, então a camada 1 entra dentro dele.

Nenhuma das três é LLM. Presidio mais spaCy resolve sozinho a maior parte, e eu usaria o
gazetteer como rede de segurança porque NER de português erra em nome incomum.

### 7.3 Substituição consistente

Não apague, **substitua por pseudônimo estável**, senão o texto perde a estrutura e o
classificador passa a medir outra coisa:

```
pseudonimo(nome) = FAKER_POOL[ HMAC_SHA256(salt, normaliza(nome)) mod len(FAKER_POOL) ]
```

- `normaliza`: minúscula, sem acento, sem sobrenome duplicado.
- `salt` **por documento**: a mesma pessoa é consistente dentro do relato e não é
  rastreável entre relatos. É o padrão correto para canal de denúncia.
- `salt` **global**: consistente entre documentos, útil para investigação, péssimo para
  privacidade. Só com decisão explícita.
- O `salt` nunca entra no repositório, só em variável de ambiente.

Trocar "Marina Souza" por "Beatriz Campos" preserva quantidade de tokens, gênero gramatical
e formato. Trocar por `[NOME]` não preserva, e muda o que o modelo enxerga.

### 7.4 Como saber se funciona

Canários: a gramática planta PII conhecida em posições conhecidas. O teste de CI roda o
anonimizador e falha se o recall não for 100% nos canários. Recall de PII é a métrica, não
precisão: deixar passar um CPF é grave, esconder uma palavra a mais não é.

Escrever em `docs/anonimizacao.md`, com todas as letras: **anonimização automática não é
garantia**. NER erra. Para dado real saindo do perímetro, isso é decisão de compliance com
revisão humana, não um `pip install`. No repositório público só entra sintético.

## 8. A comparação de custo

### 8.1 Matriz de modelos

| Papel | Modelo | Observação |
|---|---|---|
| System One | `typesafe/jev-1.13` | US$ 0,042 por milhão de tokens de entrada, saída gratuita, janela de 32k |
| Fronteira EUA | `openai/gpt-5.6-sol` | teto de qualidade |
| Fronteira EUA | `anthropic/claude-opus-5` | segundo teto, verifica se o resultado é do modelo ou da família |
| Barato EUA | `openai/gpt-5.6-luna` | o concorrente honesto do Jev em custo |
| Fronteira China | `deepseek/deepseek-v4.1-flash` | referência de custo-benefício |
| Fronteira China | `qwen/qwen3.8-27b` | segunda referência, aberto |

Rodar todos via OpenRouter, para que o preço venha de uma fonte só e a comparação seja
justa. O Jev também está lá, o que permite usar uma chave única.

### 8.2 Preços fixados

Preço muda. Salvar `precos/openrouter-AAAA-MM-DD.json` com a data da coleta, e todo
resultado publicado referenciar o arquivo de preço que usou. Sem isso o artigo apodrece em
três meses e ninguém consegue reproduzir o número.

### 8.3 As métricas que vão para o artigo

Custo por si só engana. Registrar, por modelo e por caso:

1. **Custo por mil denúncias triadas**, em dólar e em real.
2. **Recall de nível 3**, que é a métrica que decide se dá para usar em produção.
3. **Custo por nível 3 corretamente detectado**, que é a divisão das duas acima e a única
   métrica que responde a pergunta de negócio.
4. **Latência p50 e p95**.
5. **Chamadas por decisão**, separadas entre System One e LLM.
6. **Taxa de hand-off**, quando houver arranjo com `FallbackModel`. Um arranjo que
   entrega quase tudo para o modelo caro paga as duas contas e fica mais lento que não
   usar Jev nenhum. Essa taxa é o que expõe isso.
7. **Estabilidade à ordem**: o mesmo caso com as opções permutadas. A ordem das opções faz
   parte do que o modelo vê e reordenar pode mudar a resposta. Classificador que não
   sobrevive à permutação não vai para produção, e quase ninguém testa isso.
8. **Calibração**: as probabilidades que voltam em `provider_details`, comparadas com o
   acerto real. Um modelo confiante e errado é pior que um modelo inseguro e errado.

### 8.4 Cuidado de metodologia

Rodar cada caso com repetição (`Dataset.evaluate` aceita múltiplas execuções) e reportar
dispersão. Chamada repetida com entrada idêntica move as probabilidades em alguns
centésimos, e sem repetição você publica ruído como diferença.

## 9. Regras de trabalho neste repositório

1. Nada de dado real de cliente, relato real ou conteúdo de produção do Sigilo, em nenhum
   arquivo, em nenhum commit, nem em exemplo de docstring.
2. O nome do produto não aparece em caminho de pasta, nome de arquivo ou nome de variável.
   Use `canal-de-denuncia`. No texto do artigo, quando fizer sentido, aí sim.
3. `resultados/` é versionado, para que qualquer pessoa leia os números sem ter chave.
4. Nenhuma chave de API no repositório. `.env.example` com as variáveis vazias.
5. Todo número publicado precisa dizer: versão do modelo, data do preço, tamanho do
   dataset, número de repetições.
6. Commits em português, mensagem no imperativo.

## 10. Tarefas, em ordem

**Tarefa 1: fundação.** `pyproject.toml` com `uv`, `.gitignore` de Python, `.env.example`,
`LICENSE-CONTENT` com CC BY 4.0, README longo substituindo a linha atual, e a árvore de
pastas com `__init__.py`. Sem lógica ainda. Um commit.

**Tarefa 2: anonimizador.** Camada 1 completa com testes de dígito verificador, camada 2
com gazetteer, pseudônimo determinístico e os canários rodando em CI.

**Tarefa 3: gramática e dataset.** Gerador determinístico, `dataset.yaml` versionado,
e um relatório de distribuição de classes para conferir que não ficou desbalanceado.

**Tarefa 4: tipos e agente.** `output_type` com os seis sinais, a rubrica `IntEnum` e a
função de composição da urgência.

**Tarefa 5: runner e métricas.** CLI, cálculo de custo, avaliadores custom, comparação
contra baseline e export JSON.

**Tarefa 6: teste de permutação.** O de estabilidade à ordem das opções.

**Tarefa 7: primeira rodada e artigo.** Jev contra os cinco baselines, no sintético e no
holdout.

Parar ao fim de cada tarefa e esperar aprovação. Não antecipar tarefa seguinte.
