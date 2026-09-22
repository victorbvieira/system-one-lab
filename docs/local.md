# Rodar tudo em Docker, com o modelo local

O laboratorio inteiro roda dentro de um container. Duas razoes, e a segunda e a que motiva
este documento:

1. **Isolamento.** O modelo local traz torch, transformers e centenas de megabytes de
   pesos. Nada disso encosta no sistema de quem testa, e o que roda aqui e o mesmo que vai
   rodar na VPS depois.
2. **O relato nao sai da maquina.** Essa e a unica rota do catalogo em que um relato real
   poderia ser julgado sem uma decisao de compliance sobre mandar texto de denuncia para um
   terceiro. Vale ler a secao 5 antes de tirar conclusao sobre isso.

## 1. Subir

```bash
docker compose up lab                 # painel em http://localhost:8501
docker compose run --rm lab lab listar
docker compose --profile gpu up lab-gpu   # com a placa de video, em :8502
```

O repositorio e montado inteiro no container, entao `resultados/` aparece na sua maquina,
pronto para commitar. Os pesos ficam num volume nomeado (`system-one-lab-modelos`) e
sobrevivem a reconstrucao da imagem — sem isso, cada subida baixaria de novo.

Em Linux, exporte `UID` e `GID` antes de subir, senao os arquivos gravados saem
pertencendo ao root:

```bash
export UID=$(id -u) GID=$(id -g)
```

A imagem e grande: o `torch` traz as bibliotecas da NVIDIA mesmo quando nao ha placa. Para
a VPS isso nao serve, e o caminho la e outro — ver a secao 6.

## 2. Rodar o modelo local

```bash
docker compose run --rm lab lab rodar --modelo laya --limite 40 --repeticoes 3
docker compose --profile gpu run --rm lab-gpu lab rodar --modelo laya --dispositivo cuda
```

O checkpoint padrao e o **multilingue**. Nao e detalhe: o checkpoint raiz e em ingles e
colapsa fora do alfabeto latino, e o corpus daqui e todo em portugues.

## 3. O que muda no custo quando o modelo e seu

O resto do laboratorio calcula custo por token contra uma tabela de preco fixada. Um modelo
que roda na sua maquina nao tem preco por token: tem **preco por hora**, que corre esteja
ele ocupado ou parado. Sao dois tipos de numero diferentes, e misturar os dois sem dizer e
a maneira mais facil de publicar besteira.

Por isso:

- `precos/maquinas-AAAA-MM-DD.json` guarda o preco por hora de cada maquina. **Edite com o
  custo real da sua** antes de publicar qualquer numero.
- O custo de uma execucao local e o **relogio de parede** da avaliacao contra esse preco —
  nao a soma das latencias, que com concorrencia conta cada worker separado e multiplicaria
  a conta.
- Toda execucao passa a reportar `triagens_por_hora`, que e a vazao medida. Com ela e o
  preco da maquina, qualquer pessoa recalcula o custo no volume dela.

O padrao e a maquina `local-proprio`, a **US$ 0/hora**: hardware ja pago, custo marginal
zero. O custo por mil sai zero de proposito — nesta fase o que interessa e qualidade e
vazao, nao preco. Para comparar com as APIs, rode contra uma maquina precificada:

```bash
docker compose run --rm lab lab rodar --modelo laya --maquina t4-nuvem
```

Duas ressalvas honestas sobre esse numero:

- O relogio de parede de uma execucao curta **inclui a carga fria** do checkpoint, de 7 a 10
  segundos (ate quase um minuto na primeira vez, com o disco frio). Um servico que fica de
  pe amortiza isso; um benchmark de 40 casos, nao. O custo local de uma execucao pequena e
  pessimista.
- O custo por decisao de um modelo auto-hospedado depende de **utilizacao**, que e uma
  variavel que nao existe para API. Saturado, ele e barato. Ocioso, e o arranjo mais caro da
  tabela: uma GPU parada custa o mesmo que uma GPU trabalhando.

## 4. Zero-shot nao e o numero do Laya

O proprio model card diz, com todas as letras, que o Laya e "a fast base to specialise, not
a zero-shot decision engine". Os numeros publicados:

| | Laya multilingue |
|---|---|
| typed-decisions, zero-shot | 0,352 |
| baseline de classe majoritaria | 0,461 |
| typed-decisions, apos fine-tuning | 0,766 |

Ou seja: **zero-shot, ele perde para chutar a classe majoritaria**. O 0,766 do comparativo
contra o Jev e depois de afinar.

Ha dois jeitos errados de publicar isso, e eles erram em direcoes opostas:

- Laya zero-shot contra Jev zero-shot, concluindo que o open source perde feio.
- Laya afinado contra Jev zero-shot, concluindo que ganha.

Os dois sao noticia e nenhum e verdade. O desenho honesto tem tres bracos, rotulados:
Jev zero-shot, Laya zero-shot e Laya afinado — e o braco afinado **so pode ser medido no
holdout**. Afinar na gramatica sintetica e avaliar na gramatica sintetica nao mede nada: a
gramatica estaria se avaliando. Isso torna o `holdout.yaml` pre-requisito, nao opcional.

Uma terceira coisa a declarar: o Laya precisa de **ajuste de temperatura** por (tipo de
pergunta, numero de opcoes) para calibrar — o ECE do multilingue cai de 0,314 para 0,106
com isso. Ajustar para um modelo e nao para o outro e dar uma mao a um so. O certo e
ajustar para ambos, num conjunto separado do de avaliacao, e reportar cru e ajustado.

### O que ja se viu aqui

Uma rodada de 10 casos, uma repeticao, CPU, zero-shot, so para ver o caminho funcionar:
acuracia composta 0,125, recall de nivel 3 igual a zero, e acuracia de 0,10 no campo de
hierarquia. Bate com o que o card avisa. **Nao e resultado publicavel** — dez casos nao sao
amostra — e por isso nao esta em `resultados/`.

## 5. O argumento de privacidade, com o tamanho certo

E verdade e e importante: com o modelo local, o texto do relato nao sai da maquina. Nenhuma
das outras rotas do catalogo pode dizer isso.

Tres limites que precisam ser ditos junto:

1. **Neste repositorio nao muda nada**, porque o corpus e sintetico. Nao ha PII de ninguem
   para vazar em lugar nenhum. O ganho e para o pipeline de producao que isto ensaia.
2. **Local nao e sinonimo de seguro.** O relato continua em disco, em log, em memoria e no
   proprio `resultados/`. Se um dia houver relato real, os tracos gravados passam a conter
   texto real — e `resultados/` e versionado e publico.
3. **Modelo local nao substitui o anonimizador.** Ele resolve "o texto nao vai para
   terceiro"; nao resolve "quem tem acesso ao disco le tudo". Os dois juntos e que formam o
   argumento: PII removida antes, e julgamento sem sair do perimetro. Ver
   `docs/anonimizacao.md`, e o aviso que abre aquele documento.

Para o artigo, a frase defensavel e: *entre os modelos comparados, o local e o unico que
poderia julgar um relato real sem uma decisao de compliance sobre envio a terceiros.* Nao:
*modelo local e seguro.*

## 6. Quando for para a VPS

O caminho na VPS nao e este container. O Laya tem runtime em **ONNX Runtime**, que dispensa
torch e Python no servidor e e mais rapido em CPU. A imagem de producao deve ser construida
sobre ele, e nao sobre os 5 GB de wheels com CUDA que este container carrega para poder
usar a sua placa.

O ponto de virada economico, com as latencias publicadas e uma VPS de 4 vCPU a cerca de
US$ 20 por mes: a VPS empata com a API por volta de **1.000 a 1.300 triagens por hora
sustentadas**. Abaixo disso a API sai mais barata; acima, o auto-hospedado ganha por uma
ordem de grandeza. Se a VPS ja existe e ja esta paga, o custo marginal e praticamente zero e
a conta e outra — o que tambem e um resultado publicavel, e provavelmente o mais util para
quem le.
