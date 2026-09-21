# system-one-lab

Benchmarking System One models against LLMs for typed decisions in Python.

Laboratorio publico e reproduzivel para uma pergunta so: **em decisoes tipadas,
um modelo System One dedicado entrega a mesma qualidade que um LLM de fronteira,
e por quanto menos? E onde ele falha?**

Mantido por Victor Vieira (BIDU Gestao e Participacoes). Serve de base para
artigos tecnicos.

---

## O que e um modelo System One

Um modelo System One nao escreve texto. Ele recebe um **estado** (o material a
julgar) e **perguntas tipadas**, e devolve cada resposta com uma **confianca** e
a **distribuicao de probabilidades** por opcao. Nao ha prosa para parsear, nao ha
JSON para consertar: o tipo e o contrato.

Isso muda o que da para medir. Da para perguntar se o modelo estava confiante
quando errou, e da para permutar a ordem das opcoes e ver se a resposta aguenta.

Aqui o System One e o **Jev**, da TypeSafe, na versao fixada
`typesafe:jev-1.13.0`. Os baselines sao LLMs de fronteira e de baixo custo,
rodados via OpenRouter.

## O que este repositorio NAO e

**Nao e uma comparacao definitiva entre modelos.** Os datasets sao pequenos, o
dominio e unico e a rotulagem e de uma pessoa. Os numeros aqui dizem algo sobre
*esta* tarefa, *neste* dominio, *nesta* versao dos modelos, e nada alem disso.

Este paragrafo se repete em todo artigo que sair daqui. Nao e modestia de
formulario: um benchmark de dominio unico que se apresenta como geral e pior que
benchmark nenhum.

## Caso 1: grau de urgencia de uma denuncia

Canal de denuncia interno. Chega um relato em texto livre, em portugues, e a
decisao e o **grau de urgencia da apuracao**, numa rubrica ordinal de quatro
niveis:

| Nivel | Nome | Significado |
|---|---|---|
| 0 | rotina | apurar no fluxo normal, sem prazo especial |
| 1 | relevante | apurar dentro da semana |
| 2 | grave | apurar em 24 horas; envolve continuidade, hierarquia ou varios afetados |
| 3 | critico | risco fisico, retaliacao em curso ou ilicito em andamento; resposta imediata |

### A regra de ouro do desenho

**Nao se pergunta "qual a urgencia?" em um campo so.** Uma pergunta que pesa
varias coisas ao mesmo tempo nao da erro: devolve um numero plausivel com
confianca baixa, e voce descobre tarde.

Entao perguntamos os **sinais separados**, um por campo:

- `risco_fisico_iminente` (bool)
- `em_andamento` (bool) - o fato continua acontecendo
- `retaliacao` (bool) - ha ameaca ou punicao contra quem relata
- `hierarquia_do_acusado` (par, gestor direto, alta lideranca, externo)
- `afetados` (uma pessoa, um time, a empresa toda, indeterminado)
- `tem_evidencia` (bool) - o relato cita anexo, testemunha ou registro

E a urgencia final sai de uma **funcao deterministica em Python** sobre esses
campos. Tres ganhos: o rotulo vira auditavel, a rubrica fica discutivel com o
juridico, e quando o modelo erra voce sabe **qual sinal** ele errou.

O campo composto tambem e pedido direto ao modelo, em paralelo, so para comparar
as duas abordagens no artigo.

### Limiares assimetricos

Um falso negativo em nivel 3 custa muito mais que um falso positivo. Por isso o
`typesafe_boolean_threshold` desce nos campos de risco - um `True` so precisa ser
plausivel - e a metrica principal do caso e **recall de nivel 3**, nao acuracia
media.

## Nenhum LLM escreve os dados deste repositorio

Isso e inegociavel, por tres motivos:

1. Dado gerado por LLM carrega o vies do LLM que vai ser avaliado, e isso
   contamina o benchmark.
2. Torna o dataset irreproduzivel.
3. Levanta duvida de proveniencia num repositorio publico que fala de canal de
   denuncia.

O dataset sai de uma **gramatica combinatoria deterministica**, com semente
fixa, que combina cenario (10 tipos, de assedio moral a irregularidade
ambiental) x flags de gravidade x registro linguistico (formal, coloquial,
telegrafico, com erro de digitacao, prolixo...) x slots preenchidos pelo Faker
com locale `pt_BR`. O **rotulo sai das flags, nao do texto**.

Com ruido obrigatorio, senao o benchmark vira detector de palavra-chave:
negacoes ("nao houve ameaca nenhuma, mas quero registrar"), distratores lexicais
(palavra alarmante em contexto benigno), **eufemismo** (nivel 3 escrito de forma
contida, que e como a denuncia grave costuma chegar de verdade) e relatos
ambiguos, cujo rotulo e "indeterminado" e que entram na metrica de abstencao.

E um **holdout humano**: 60 casos escritos e rotulados a mao, fora da gramatica.
A metrica que vai no artigo e a do holdout; a do sintetico serve para iterar
rapido. Se a acuracia no sintetico for muito maior que no holdout, a gramatica
vazou o rotulo - o que e um resultado, e vale paragrafo no artigo.

Detalhes em [`docs/metodologia.md`](docs/metodologia.md).

## Anonimizacao sem LLM

O dataset do repositorio e sintetico e nao tem PII real. O pacote
`anonimizador/` existe para o pipeline que um dia vai ler relato real, e para
ser testado contra a PII que a gramatica planta de proposito.

Duas camadas, nenhuma delas LLM: regex com **validacao de digito verificador**
(um numero de processo nao vira CPF) e nomes proprios via gazetteer + NER
estatistico, com substituicao por **pseudonimo deterministico e estavel**
(HMAC-SHA256 com salt por documento). Trocar "Marina Souza" por "Beatriz Campos"
preserva quantidade de tokens, genero gramatical e formato; trocar por `[NOME]`
nao preserva, e muda o que o modelo enxerga.

**Anonimizacao automatica nao e garantia.** Ver
[`docs/anonimizacao.md`](docs/anonimizacao.md).

## Os modelos

| Papel | Modelo | Observacao |
|---|---|---|
| System One | `typesafe/jev-1.13` | US$ 0,042 por milhao de tokens de entrada, saida gratuita, janela de 32k |
| Fronteira EUA | `openai/gpt-5.6-sol` | teto de qualidade |
| Fronteira EUA | `anthropic/claude-opus-5` | segundo teto; verifica se o resultado e do modelo ou da familia |
| Barato EUA | `openai/gpt-5.6-luna` | o concorrente honesto do Jev em custo |
| Fronteira China | `deepseek/deepseek-v4.1-flash` | referencia de custo-beneficio |
| Fronteira China | `qwen/qwen3.8-27b` | segunda referencia, aberto |

Todos via OpenRouter, para que o preco venha de uma fonte so.

**A versao do modelo e sempre fixada.** Nunca `jev-latest` num resultado
publicado: os aliases movem quando a TypeSafe publica versao nova, e um limiar
calibrado contra uma versao deixa de valer na seguinte.

## As metricas que vao para o artigo

Custo por si so engana. Por modelo e por caso:

1. **Custo por mil denuncias triadas**, em dolar e em real.
2. **Recall de nivel 3** - a metrica que decide se da para usar em producao.
3. **Custo por nivel 3 corretamente detectado** - a divisao das duas acima, e a
   unica metrica que responde a pergunta de negocio.
4. **Latencia p50 e p95.**
5. **Chamadas por decisao**, separadas entre System One e LLM.
6. **Taxa de hand-off**, quando houver `FallbackModel`. Um arranjo que entrega
   quase tudo para o modelo caro paga as duas contas e fica mais lento que nao
   usar Jev nenhum; essa taxa e o que expoe isso.
7. **Estabilidade a ordem**: o mesmo caso com as opcoes permutadas. A ordem faz
   parte do que o modelo ve, e classificador que nao sobrevive a permutacao nao
   vai para producao. Quase ninguem testa isso.
8. **Calibracao**: as probabilidades de `provider_details` contra o acerto real.
   Um modelo confiante e errado e pior que um modelo inseguro e errado.

Cada caso roda com **repeticao** e reporta dispersao. Chamada repetida com
entrada identica move as probabilidades em alguns centesimos; sem repeticao voce
publica ruido como diferenca.

## Estrutura

```
system-one-lab/
  pyproject.toml
  README.md
  LICENSE                     Apache 2.0, para o codigo
  LICENSE-CONTENT             CC BY 4.0, para docs, datasets, resultados e artigos
  .env.example
  docs/
    BRIEFING.md               o briefing original do projeto
    metodologia.md            como os datasets foram feitos e por que confiar neles
    anonimizacao.md           o pipeline de PII, detalhado
  lab/
    modelos.py                registro de modelos e precos fixados
    custo.py                  custo a partir de usage + precos
    metricas.py               avaliadores custom
    permutacao.py             teste de estabilidade a ordem das opcoes
    relatorio.py              impressao, baseline e export JSON
    run.py                    CLI
  casos/
    canal-de-denuncia/        tipos, gramatica, dataset, holdout, agente
  anonimizador/
    padroes.py                regex + digito verificador
    nomes.py                  NER + gazetteer + pseudonimo deterministico
    canarios.py               PII plantada, para medir recall em CI
  precos/                     openrouter-AAAA-MM-DD.json
  resultados/                 <caso>/<modelo>/<execucao>.json e history.jsonl
  artigos/
```

## Como rodar

Requer Python 3.12+ e [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/victorbvieira/system-one-lab
cd system-one-lab
uv sync                       # ambiente + dependencias
cp .env.example .env          # preencha OPENROUTER_API_KEY
```

Gerar o dataset sintetico (deterministico, nao precisa de chave nem de rede):

```bash
uv run python casos/canal-de-denuncia/gerar.py
```

Rodar uma avaliacao e comparar contra baselines:

```bash
uv run lab --caso canal-de-denuncia --modelo typesafe:jev-1.13.0 --repeticoes 5
uv run lab --caso canal-de-denuncia --comparar --repeticoes 5
```

Extras opcionais:

```bash
uv sync --extra ner           # spaCy e Presidio, para a camada 2 do anonimizador
uv sync --extra obs           # Langfuse, nunca obrigatorio para rodar
```

Testes e lint:

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

## Regras de trabalho neste repositorio

1. Nada de dado real de cliente, relato real ou conteudo de producao, em nenhum
   arquivo, em nenhum commit, nem em exemplo de docstring.
2. Nome de produto nao aparece em caminho de pasta, nome de arquivo ou nome de
   variavel. Use `canal-de-denuncia`.
3. `resultados/` e versionado, para que qualquer pessoa leia os numeros sem ter
   chave.
4. Nenhuma chave de API no repositorio. `.env.example` com as variaveis vazias.
5. Todo numero publicado diz: versao do modelo, data do preco, tamanho do
   dataset e numero de repeticoes.
6. Commits em portugues, mensagem no imperativo.
7. Codigo e docstrings em ingles; README, docs e artigos em portugues; dados em
   portugues.

## Estado

| Tarefa | Entrega | Situacao |
|---|---|---|
| 1 | Fundacao: `pyproject.toml`, `.gitignore`, `.env.example`, licencas, README, arvore de pastas | feito |
| 2 | Anonimizador: camadas 1 e 2, canarios em CI | a fazer |
| 3 | Gramatica e `dataset.yaml`, com relatorio de distribuicao de classes | a fazer |
| 4 | Tipos e agente: os seis sinais, a rubrica `IntEnum`, a composicao da urgencia | a fazer |
| 5 | Runner e metricas: CLI, custo, avaliadores custom, export JSON | a fazer |
| 6 | Teste de permutacao | a fazer |
| 7 | Primeira rodada e artigo | a fazer |

## Licenca

Codigo sob [Apache License 2.0](LICENSE). Conteudo - docs, datasets, resultados
e artigos - sob [CC BY 4.0](LICENSE-CONTENT).
