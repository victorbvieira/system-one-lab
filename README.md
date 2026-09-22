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
| System One aberto | `convaiinnovations/laya` (multilingue) | 421M, ModernBERT, Apache 2.0, rodando nesta maquina. Sem custo por token e sem mandar o relato para ninguem |
| System One | `typesafe/jev-1.13` | US$ 0,042 por milhao de tokens de entrada, saida gratuita, janela de 32k |
| Fronteira EUA | `openai/gpt-5.6-sol` | teto de qualidade |
| Fronteira EUA | `anthropic/claude-opus-5` | segundo teto; verifica se o resultado e do modelo ou da familia |
| Barato EUA | `openai/gpt-5.6-luna` | o concorrente honesto do Jev em custo |
| Fronteira China | `deepseek/deepseek-v4.1-flash` | referencia de custo-beneficio |
| Fronteira China | `qwen/qwen3.8-27b` | segunda referencia, aberto |

Os baselines rodam via OpenRouter, para que o preco venha de uma fonte so. **O Jev nao**:
ele nao e servido pelo OpenRouter, e um modelo System One alcancado por um endpoint de chat
devolveria a resposta sem a confianca e sem a distribuicao de probabilidades por tras dela —
que e metade do que ha para medir. Entao o Jev vai pela API nativa da TypeSafe, e o preco
dele vem do model card, em `precos/typesafe-AAAA-MM-DD.json`.

O **Laya** nao e uma API: e um modelo aberto que roda em Docker na sua maquina. Isso muda o
eixo de custo — nao ha preco por token, ha preco por hora, que corre com a maquina parada —
e muda o que da para fazer com dado real: e a unica rota do catalogo em que o relato nao sai
do perimetro. Ver [`docs/local.md`](docs/local.md), inclusive para por que o numero
zero-shot dele nao e o numero dele.

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
  docker/
    Dockerfile                o laboratorio inteiro, isolado
  docker-compose.yml          servico sem placa e servico com placa
  docs/
    BRIEFING.md               o briefing original do projeto
    metodologia.md            como o dataset foi feito e por que confiar nele
    painel.md                 como rodar, inspecionar e publicar
    local.md                  Docker, modelo local, custo por hora e privacidade
    holdout.md                como escrever o holdout, e por que nao da para gera-lo
    anonimizacao.md           o pipeline de PII, detalhado
  lab/
    esquemas.py               docstring de membro de enum vira descricao no JSON Schema
    casos.py                  carrega o caso de uma pasta com hifen no nome
    holdout.py                esquema e validador do holdout escrito a mao
    modelos.py                catalogo de modelos, rotas e ajustes
    laya.py                   rota local: o modelo aberto como modelo do Pydantic AI
    precos.py                 tabelas de preco fixadas, por data
    custo.py                  custo a partir de usage + precos
    confianca.py              recupera a probabilidade bruta e aplica limiar assimetrico
    tracos.py                 passos, tools e detalhes do provedor de uma execucao
    metricas.py               avaliadores Pydantic Evals e metricas agregadas
    execucao.py               roda um modelo sobre um corpus e monta o resultado
    resultados.py             o formato do arquivo de resultado
    relatorio.py              impressao e comparacao no terminal
    dashboard.py              exporta o HTML estatico
    painel/                   painel local em Streamlit
    permutacao.py             teste de estabilidade a ordem das opcoes (a fazer)
    run.py                    CLI
  casos/
    canal-de-denuncia/        tipos, gramatica, dataset, holdout, agente
  anonimizador/
    padroes.py                regex + digito verificador
    nomes.py                  NER + gazetteer + pseudonimo deterministico
    canarios.py               PII plantada, para medir recall em CI
  precos/                     preco por token das APIs e preco por hora das maquinas
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
uv run lab listar                                        # modelos, chaves, execucoes
uv run lab rodar --modelo jev --repeticoes 3 --limite 40
uv run lab rodar --comparar --repeticoes 3               # todos os que tiverem chave
uv run lab comparar --ultimas 1                          # compara o que ja foi gravado
```

Rodar tudo em Docker, que e como o modelo local roda isolado:

```bash
export UID=$(id -u) GID=$(id -g)
docker compose up lab                                    # painel em :8501
docker compose run --rm lab lab rodar --modelo laya --limite 40
docker compose --profile gpu up lab-gpu                  # com placa de video, em :8502
```

Abrir o painel local, que configura os agentes, roda, e mostra passo a passo o que o
modelo fez — incluindo as tools chamadas e a confianca de cada campo:

```bash
uv sync --extra painel
uv run lab painel                                        # http://localhost:8501
```

Escrever e validar o holdout, que e o corpus cuja metrica vai no artigo:

```bash
uv run lab holdout                    # valida e mostra a distribuicao
uv run lab painel                     # aba "Holdout": escreve um caso por vez
```

Exportar o dashboard estatico, que e o arquivo que vai versionado e publicado:

```bash
uv run lab dashboard                                     # resultados/<caso>/dashboard.html
```

Extras opcionais:

```bash
uv sync --extra ner           # spaCy e Presidio, para a camada 2 do anonimizador
uv sync --extra obs           # Langfuse, nunca obrigatorio para rodar
```

Detalhes de cada opcao em [`docs/painel.md`](docs/painel.md).

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
| 3 | Gramatica e `dataset.yaml`: 1.120 casos balanceados, com metodologia escrita | feito |
| 4 | Tipos e agente: os seis sinais, a rubrica `IntEnum`, a composicao da urgencia | feito |
| 5 | Runner e metricas: CLI, custo, avaliadores, export JSON | feito |
| — | Integracao com o Jev, painel local e dashboard estatico | feito |
| — | Rota local (Laya em Docker), custo por hora e vazao medida | feito |
| — | Ferramental do holdout: esquema, validador e editor no painel | feito |
| 2 | Anonimizador: camadas 1 e 2, canarios em CI | a fazer |
| 6 | Teste de permutacao: estabilidade a ordem das opcoes | a fazer |
| 7 | Primeira rodada com chave e artigo | a fazer |

O **holdout** tem esquema, validador e editor no painel; faltam os 60 relatos, que sao
trabalho manual por definicao. Ver [`docs/holdout.md`](docs/holdout.md).

Os canarios de PII ja estao plantados no dataset, com o valor exato registrado em cada
caso, esperando o anonimizador da Tarefa 2.

## O que da para ver

Depois de uma rodada, `resultados/<caso>/dashboard.html` e uma pagina autocontida — sem
CDN, sem build, sem servidor — com recall de nivel 3, custo por denuncia critica detectada,
custo contra qualidade, acuracia por sinal, curva de calibracao, latencia p50 e p95 e a
matriz de confusao de cada modelo. Ela e versionada junto com os numeros que mostra.

Um modelo que nao reporta confianca aparece na calibracao como ausencia de medida, nunca
como zero: nao poder ser calibrado e um achado sobre o modelo, e some se virar um numero.

Para o modelo local ha tambem `triagens_por_hora`, a vazao medida. Com ela e o preco da
maquina, qualquer pessoa recalcula o custo no volume dela — que e a conta que importa, e que
nao existe para uma API.

## Licenca

Codigo sob [Apache License 2.0](LICENSE). Conteudo - docs, datasets, resultados
e artigos - sob [CC BY 4.0](LICENSE-CONTENT).
