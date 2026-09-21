# Painel, execucao e dashboard

Como rodar os testes localmente, ler o que o modelo fez passo a passo, e publicar os
numeros. O fluxo inteiro e local: nada aqui depende de servico externo alem das APIs dos
modelos, e os resultados sao arquivos versionados.

## 1. Preparar

```bash
uv sync --extra painel      # ambiente + Streamlit
cp .env.example .env        # preencha as chaves
```

Duas chaves, e elas nao sao intercambiaveis:

| Variavel | Para que | Obrigatoria? |
|---|---|---|
| `TYPESAFE_API_KEY` | o Jev, na API nativa da TypeSafe | so para rodar o System One |
| `OPENROUTER_API_KEY` | todos os baselines | so para rodar os baselines |

**O Jev nao e servido pelo OpenRouter.** Alem disso, um modelo System One alcancado por um
endpoint de chat devolveria uma resposta sem a confianca nem a distribuicao de
probabilidades por tras dela — que e a metrica 8 e metade do que ha para dizer no artigo.
Por isso a rota nativa, e por isso o preco do Jev vem do model card da TypeSafe, em
`precos/typesafe-AAAA-MM-DD.json`, enquanto os baselines vem da coleta do OpenRouter.

## 2. Rodar pela linha de comando

```bash
uv run lab listar                                  # modelos, chaves presentes, execucoes
uv run lab rodar --modelo jev --repeticoes 3 --limite 40
uv run lab rodar --comparar --repeticoes 3         # todos os modelos com chave disponivel
uv run lab rodar --modelo jev --atras sol          # mede hand-off com FallbackModel
uv run lab comparar --ultimas 1                    # compara execucoes ja gravadas
uv run lab dashboard                               # exporta o HTML estatico
```

Opcoes que mudam o que o numero significa, e que por isso ficam gravadas no resultado:

- `--limite` sorteia um subconjunto **estratificado por nivel**. Um subconjunto aleatorio
  de um corpus balanceado nao e balanceado, e um recall de nivel 3 sobre nove casos de
  nivel 3 nao e um numero publicavel. `--limite 0` roda os 1.120 casos.
- `--repeticoes` roda cada caso varias vezes e reporta a dispersao. Com uma passagem so,
  publica-se ruido como diferenca.
- `--limiar-de-risco` e o limiar mais baixo dos campos de risco. Aplicado **depois** da
  resposta, nao numa segunda chamada: a probabilidade bruta de cada booleano e recuperavel
  da confianca reportada e do limiar em que foi medida.
- `--tracos` decide quanto historico guardar. `amostra` (padrao) guarda os primeiros casos
  e todas as falhas; `todos` guarda tudo, e o historico de mensagens de uma execucao
  inteira poe centenas de megabytes num repositorio versionado.

## 3. O painel

```bash
uv run lab painel      # http://localhost:8501
```

Tres abas, na ordem em que o trabalho acontece:

**Configurar e rodar.** Escolhe caso, corpus (sintetico ou holdout), modelos, repeticoes,
tamanho da amostra, filtros de cenario e registro, os dois limiares e as instrucoes do
agente. As instrucoes sao **as mesmas para todos os modelos** — se variarem por modelo, a
comparacao passa a medir o arranjo, nao o modelo.

**Execucoes.** Abre uma execucao gravada e mostra, por caso:

- o relato exatamente como o modelo o recebeu;
- cada sinal com esperado, obtido, acerto, confianca e a probabilidade de sim recuperada;
- a urgencia esperada, a composta pelos sinais, a perguntada direto e a regra que decidiu;
- o que o limiar de risco mudaria, quando muda;
- a distribuicao de probabilidades por opcao, quando o modelo reporta;
- **os passos**: cada requisicao e resposta, com tokens, motivo do fim, as tools chamadas e
  seus argumentos, e os detalhes que o provedor devolveu.

E o filtro "so os casos em que o modelo errou a urgencia", que e por onde se comeca a
olhar.

**Dashboard.** Mostra o mesmo HTML que `lab dashboard` exporta e que vai versionado, e tem
um botao para grava-lo em `resultados/<caso>/dashboard.html`. Ser o mesmo arquivo e
proposital: o que se revisa aqui e o que se publica nao podem divergir.

## 4. Publicar

```bash
uv run lab rodar --comparar --repeticoes 5 --limite 200
uv run lab dashboard
git add resultados/ && git commit -m "Registre a rodada de <data>"
```

`resultados/` e versionado para que qualquer pessoa leia os numeros sem ter chave. Cada
arquivo de resultado carrega, por construcao, as quatro coisas que um numero publicado
precisa dizer:

1. a versao do modelo — a pedida e a que de fato respondeu;
2. o arquivo de preco e a data da coleta, inclusive do cambio;
3. o dataset, sua semente, o hash da gramatica e quantos casos entraram;
4. o numero de repeticoes e os ajustes usados.

Mais o commit do repositorio e as versoes das bibliotecas, em `ambiente`.

O `dashboard.html` e autocontido: sem CDN, sem build, sem servidor. Abre do disco e
publica no GitHub Pages como esta.

## 5. O que o dashboard mostra

| Grafico | O que responde |
|---|---|
| Recall de nivel 3 | quantas denuncias criticas o modelo capturou |
| Custo por nivel 3 detectado | a unica metrica que responde a pergunta de negocio |
| Custo contra qualidade | onde cada modelo cai no plano preco x acerto |
| Acuracia por sinal | **qual** campo o modelo erra, nao so que errou |
| Calibracao | se a confianca reportada corresponde ao acerto real |
| Latencia p50 e p95 | a mediana e o que o usuario sente nos piores dias |
| Matriz de confusao | para onde vaza o erro, com o nivel 3 em destaque |

Um modelo que nao reporta confianca aparece na calibracao como **ausencia de medida**,
nunca como zero. Nao poder ser calibrado — nem roteado por confianca — e um achado sobre o
modelo, e some se virar um numero.
