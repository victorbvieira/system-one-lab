# Metodologia do dataset sintetico

Este documento explica como o `dataset.yaml` do caso `canal-de-denuncia` foi feito e por
que confiar nele — e onde nao confiar. Todo numero publicado a partir dele depende do que
esta escrito aqui.

Estado: vale para a versao `1` do formato, semente `20260921`, gramatica `8d429b6cf953b74d`.

## 1. A regra que decide tudo: nenhum LLM escreve os dados

Nenhum texto deste repositorio foi escrito por um modelo de linguagem. Nem um relato, nem
um fragmento, nem um exemplo de docstring. Tres motivos:

1. **Contaminacao.** Dado gerado por LLM carrega o vies do LLM que vai ser avaliado. Medir
   o GPT em texto escrito pelo GPT mede parentesco, nao competencia.
2. **Reprodutibilidade.** Uma chamada de API nao se repete igual. Uma gramatica com semente
   fixa se repete byte a byte, e ha um teste que cobra isso a cada execucao da CI.
3. **Proveniencia.** Num repositorio publico que fala de canal de denuncia, "de onde veio
   este texto?" precisa ter uma resposta curta e verificavel.

O texto sai de uma gramatica combinatoria; os nomes, datas, valores e documentos saem do
Faker com locale `pt_BR` e semente fixa.

## 2. O rotulo sai das flags, nunca do texto

Esta e a inversao que faz o dataset ser auditavel. O gerador **primeiro** escolhe a
combinacao de sinais, **depois** escreve um texto que expressa aquela combinacao:

```
combinacao de sinais  ->  compor_urgencia()  ->  rotulo
        |
        +-------------->  frases que expressam cada sinal  ->  texto
```

O rotulo nunca e opiniao de quem leu. E a saida de `compor_urgencia`, a funcao
deterministica em `casos/canal-de-denuncia/tipos.py`, aplicada a flags que o gerador
escolheu antes de existir texto. Cada caso guarda a regra que decidiu (`R1` a `R7`), e um
teste reaplica a funcao a todos os 1.120 casos para garantir que o arquivo nao ficou para
tras de uma mudanca na regra.

A escada, na ordem em que e avaliada:

| Regra | Nivel | Quando |
|---|---|---|
| R1 | 3 critico | ha risco fisico iminente |
| R2 | 3 critico | ha retaliacao e o fato continua acontecendo |
| R0 | abstencao | um sinal necessario para decidir ficou indeterminado |
| R3 | 2 grave | houve retaliacao, ainda que encerrada |
| R4 | 2 grave | continua acontecendo e envolve hierarquia superior ou varias pessoas |
| R5 | 2 grave | hierarquia superior e varias pessoas, mesmo sem continuidade |
| R6 | 1 relevante | um agravante isolado |
| R7 | 0 rotina | episodio isolado, entre pares, com uma pessoa afetada |

A escada e deliberadamente sensivel: R1 dispara sozinha. Um unico falso positivo em
`risco_fisico_iminente` transforma um caso de rotina num alarme de nivel 3. Isso e escolha,
nao descuido — em triagem de denuncia, errar para cima custa uma apuracao a mais e errar
para baixo custa alguem. Mas significa que **recall de nivel 3 sozinho nao basta**: e
preciso ler a precisao ao lado dele, e as duas estao no dashboard uma do lado da outra.

`tem_evidencia` e perguntado e medido, mas **nao entra na escada**: evidencia muda como se
apura, nao em quanto tempo se comeca. Deixar isso escrito e o que impede o campo de virar
um criterio de desempate silencioso seis meses depois.

## 3. As quatro dimensoes da combinacao

| Dimensao | Valores | Onde fica |
|---|---|---|
| Cenario | 10, de assedio moral a irregularidade ambiental | `gramatica/cenarios.yaml` |
| Sinais | 6 campos: 4 booleanos, hierarquia (5 opcoes), afetados (4 opcoes) | `gramatica/sinais.yaml` |
| Registro | 8 formas de escrever a mesma coisa | `gramatica/registros.yaml` |
| Slots | nomes, cargos, setores, datas, valores, locais, sistemas | Faker `pt_BR` + `gramatica/slots.yaml` |

O espaco completo de combinacoes de sinais tem 320 pontos. Sortear ao acaso desse espaco
produziria um dataset desbalanceado, porque os niveis nao sao igualmente provaveis. Entao o
sorteio e **estratificado por nivel**: tres combinacoes por nivel, por cenario, mais duas de
abstencao. O resultado e balanceado por construcao, e a distribuicao publicada prova.

As frases de sinal sao **compartilhadas entre os cenarios**, de proposito. Se cada cenario
tivesse a sua forma de dizer "isso continua acontecendo", o modelo poderia acertar o sinal
reconhecendo o cenario em vez de ler a frase.

## 4. O ruido, que e o que faz o benchmark valer alguma coisa

Sem ruido, um benchmark de triagem mede se o modelo reconhece palavra alarmante. Quatro
tipos entram de proposito:

- **Negacao explicita** (672 casos): *"Nao houve ameaca nenhuma nem nada fisico, mas quero
  registrar assim mesmo."* Quem casa a palavra "ameaca" erra aqui.
- **Distrator lexical** (160 casos, so em nivel 0 e 1): palavra alarmante em contexto
  benigno — *"o cara e tiro, entrega tudo no prazo"*. Num nivel 3 nao provaria nada.
- **Eufemismo** (472 casos, com peso maior nos niveis 2 e 3): o fato grave dito de forma
  contida, sem nenhuma palavra alarmante — *"Ele fechou a porta da sala e so deixou ela
  sair depois de terminar o que queria dizer."* E como a denuncia grave costuma chegar de
  verdade, e e onde o benchmark decide.
- **Ambiguidade** (160 casos): o texto nao permite concluir. O rotulo e `null`, e o caso
  entra na metrica de **abstencao**, nunca na de acuracia. Sao de dois tipos: hierarquia ou
  alcance indeterminados (`R0`), e um sinal booleano que o texto deixa em aberto
  (`R-ambiguo`).

Omissao tambem e ruido: um booleano falso tem 40% de chance de simplesmente nao ser
mencionado, que e como a maioria dos relatos reais e escrita. Os campos de escolha nunca
sao omitidos, porque ausencia neles se leria como indeterminado — que e outro rotulo.

## 5. Os oito registros

`formal`, `coloquial`, `telegrafico`, `com_erro_de_digitacao`, `maiusculas_misturadas`,
`giria_regional`, `muito_curto`, `prolixo`. Cada combinacao de sinais aparece nos oito, com
o mesmo rotulo: 140 casos por registro.

Uma regra que o codigo garante e o teste cobra: **nenhuma transformacao de registro pode
descartar uma frase de sinal.** Abertura e fechamento podem cair; o que carrega o rotulo,
nunca. Sem isso, `muito_curto` teria outro rotulo que os demais e a comparacao entre
registros nao significaria nada.

## 6. Contradicoes entre texto e rotulo, e como sao barradas

Um caso cujo texto contradiz o proprio rotulo nao mede nada — e o gerador produziu varios
deles na primeira versao. Cada um virou um teste em `tests/test_gramatica.py`:

| Defeito encontrado | Correcao |
|---|---|
| Relato dizia "nao sei quem foi" e nomeava o acusado duas frases antes | Quando `hierarquia` e indeterminada, `{pessoa}` vira "alguem" em todo o texto |
| Nucleo dizia "a equipe toda opera sem protecao" num caso rotulado "uma pessoa" | Nucleos que implicam alcance declaram `alcance` na gramatica e so entram quando o rotulo concorda |
| Frase dizia "entao nao e urgente", entregando o rotulo | Nenhuma frase opina sobre urgencia; teste barra a familia inteira de expressoes |
| "Nao guardei nada, mas foi na frente de varias pessoas" com `tem_evidencia=False` | A frase virou "foi tudo verbal e sem registro", sem testemunha implicita |
| Frase de seguranca do trabalho aparecia em caso de assedio | Pool compartilhado ficou neutro; o sabor do cenario vive so no nucleo |
| Nome sorteado sem genero produzia "o Carolina Pires e otimo" | `{pessoa}` e nome masculino, `{pessoa2}` feminino, como as frases pressupoem |
| "alguem, diretor do juridico" com hierarquia rotulada como indeterminada | A aposicao de cargo cai junto com o nome quando o relato nao sabe quem foi |

O ultimo defeito da tabela nao foi encontrado por teste nenhum: foi encontrado rodando um
modelo contra o corpus. O Laya respondeu `alta_lideranca` a um caso rotulado como
`indeterminado`, e estava certo — o texto anunciava o cargo duas frases depois de dizer que
nao sabia quem era. O rotulo e que estava errado. Virou o teste
`test_cargo_do_acusado_some_quando_a_hierarquia_e_indeterminada`.

Vale a generalizacao: **discordancia sistematica de um modelo num campo e sinal de bug no
rotulo, nao so de erro do modelo.** Antes de publicar que um modelo vai mal num sinal, leia
dez casos em que ele discorda.

## 7. PII plantada: os canarios

O dataset e sintetico e nao tem PII de ninguem. Mesmo assim, 160 casos trazem um documento
sintetico plantado em posicao conhecida — CPF, CNPJ, telefone, e-mail, CEP ou placa — e o
valor exato fica registrado em `pii.estruturada` no proprio caso. Os nomes usados ficam em
`pii.nomes`.

Isso existe para medir o **recall do anonimizador** em CI, com os valores esperados vindo do
dataset em vez de uma lista a parte que envelhece.

Uma decisao com consequencia: os registros que introduzem erro de digitacao e caixa alta
**nao tocam no trecho de PII**. Um CPF com digito trocado deixa de ser um CPF — a validacao
de digito verificador corretamente nao o reconhece —, e o portao de CI passaria a medir o
digitador em vez do anonimizador. PII que chega corrompida e um problema real e
explicitamente fora do escopo da camada deterministica.

## 8. O que esta medido e o que nao esta

**O holdout ainda nao existe.** O dataset sintetico mede se a abordagem funciona; ele nao
prova que funciona no mundo. A metrica que vai no artigo e a do `holdout.yaml`: 60 casos
escritos e rotulados a mao por Victor e pelo Henrique, sem usar a gramatica. Nao pode ser
gerado, por definicao — se fosse, nao seria holdout.

Se a acuracia no sintetico for muito maior que no holdout, a gramatica vazou o rotulo. Isso
e um resultado, nao um fracasso, e vale paragrafo no artigo.

### Ameacas a validade, por escrito

1. **Idioma.** O model card do Jev diz que a acuracia e melhor em ingles e que outros
   idiomas variam. Este dataset e todo em portugues, que e o idioma do problema real. Toda
   comparacao aqui mede os modelos *em portugues*, e nenhum numero deste repositorio pode
   ser lido como o teto de nenhum modelo.
2. **Genero fixo.** `{pessoa}` e sempre masculino e `{pessoa2}` sempre feminino, por
   concordancia das frases. Um corpus real varia, e essa variacao nao esta medida aqui.
3. **Vocabulario finito.** 40 nucleos, 71 frases de sinal. Um modelo pode ir bem aqui por
   ter visto estas construcoes, e mal em texto fora delas. E exatamente o que o holdout
   existe para detectar.
4. **Rotulagem de uma pessoa.** A escada de regras foi escrita por uma pessoa. Outra
   organizacao decidiria diferente, sobretudo em R3 e R5.
5. **Dominio unico.** Canal de denuncia interno, empresa brasileira. Nada aqui se
   generaliza para outra tarefa de classificacao.

## 9. Como reproduzir

```bash
uv run python casos/canal-de-denuncia/gerar.py          # regera o dataset.yaml
uv run pytest tests/test_gramatica.py                   # conferem as invariantes
```

As datas dos relatos saem de uma janela ancorada em `DATA_DE_REFERENCIA`, nao dos "ultimos
tres anos" contados de hoje. Uma janela que anda com o relogio torna o corpus
irreproduzivel: a mesma semente daria um arquivo diferente amanha. Foi exatamente o que o
teste de reprodutibilidade pegou, um dia depois de ser escrito.

A geracao e deterministica: mesma semente e mesma gramatica produzem o mesmo arquivo. O
`dataset.yaml` guarda a semente e o hash da gramatica, e o teste
`test_o_arquivo_versionado_e_reproduzivel_a_partir_da_semente` falha se o arquivo versionado
e a gramatica sairem de sincronia.

## 10. Distribuicao da versao atual

1.120 casos, 560 caracteres em media.

| Nivel | Casos |
|---|---|
| 0 rotina | 240 |
| 1 relevante | 240 |
| 2 grave | 240 |
| 3 critico | 240 |
| abstencao (indeterminado) | 160 |

10 cenarios x 112 casos cada; 8 registros x 140 casos cada. Por regra: R7 240, R6 240,
R1 208, R4 112, R3 88, R0 80, R-ambiguo 80, R5 40, R2 32.

As regras raras sao raras porque a combinacao que as dispara e rara no espaco — R2 exige
retaliacao e continuidade ao mesmo tempo, sem risco fisico. Vale saber disso antes de ler
qualquer recall por regra: 32 casos sao pouco para concluir coisa alguma sobre R2.
