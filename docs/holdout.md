# O holdout: como escrever, e por que ele nao pode ser gerado

O dataset sintetico mede se a abordagem funciona. Ele **nao prova que funciona no mundo**,
porque uma gramatica so testa aquilo que alguem pensou em colocar nela. O holdout e a
correcao disso: 60 relatos escritos e rotulados a mao, sem usar a gramatica. **A metrica que
vai no artigo e a daqui.**

## 1. Por que ele nao pode ser gerado

Se o holdout sair da mesma gramatica que gerou o treino, ele nao e holdout: e mais dataset.
E se sair de um LLM, carrega a ideia que aquele LLM tem de como uma denuncia soa — para
dentro do benchmark que julga LLMs. Nos dois casos ele perde a unica coisa que existe para
fazer: **detectar que a gramatica vazou o rotulo**.

O sintoma desse vazamento e a acuracia no sintetico ser muito maior que no holdout. Isso e
um resultado, nao um fracasso, e vale paragrafo no artigo. Mas so aparece se os dois corpus
forem mesmo independentes.

Por isso nenhuma parte deste repositorio escreve relato de holdout, e o validador recusa um
arquivo que tenha voltado a ser gerado.

## 2. Como escrever

Pelo painel, que e o caminho rapido:

```bash
uv run lab painel        # aba "Holdout"
# ou, em Docker:
docker compose up lab
```

A aba mostra o progresso, o formulario e — a parte que importa — a **urgencia composta ao
vivo** conforme voce marca os seis sinais, com a regra que disparou e o motivo dela em
portugues. A urgencia nunca e digitada. Se o resultado surpreender, ou o texto diz outra
coisa, ou a regra precisa ser discutida com o juridico; as duas conversas sao melhores que
digitar um numero.

Pela linha de comando:

```bash
uv run lab holdout --iniciar --autor "Victor Vieira" --autor "Henrique"
uv run lab holdout                 # valida e mostra a distribuicao
```

### As regras, em ordem de importancia

1. **Escreva como o relato chegaria.** Na voz de quem denuncia, no registro que essa pessoa
   usaria, com o tamanho que ela escreveria. Um holdout todo em portugues de escritorio
   mede menos do que parece.
2. **Nao copie frase da gramatica.** Nem parafraseie de memoria — o validador pega seis
   palavras seguidas iguais, e pega tambem parafrase proxima. (Aconteceu ao escrever os
   proprios testes deste modulo: um texto de fixture caiu na checagem porque parafraseava
   uma frase da gramatica sem que o autor percebesse.)
3. **Nao use dado real de ninguem.** O holdout e inventado. Nome, CPF, telefone, e-mail,
   endereco: nada de gente de verdade. O validador avisa quando encontra algo com essa cara.
4. **Marque os sinais pelo que o texto afirma**, nao pelo que voce sabe ou imagina sobre o
   caso. Se o texto nao permite concluir, use `indeterminado` ou marque o sinal como
   ambiguo — o caso vai para a metrica de abstencao, que e onde ele mede alguma coisa.
5. **Assine.** O autor de cada caso fica gravado. "Rotulagem de uma pessoa" e uma limitacao
   declarada do estudo; saber de qual pessoa e o que permite medi-la depois.

### Quantos, e de que tipo

Alvo de 60 casos, com **ao menos 10 por nivel**. Abaixo disso nao da para publicar metrica
por nivel: recall de nivel 3 sobre seis casos nao e um numero, e um palpite com casas
decimais.

Escreva tambem os casos dificeis de proposito, que sao os que separam os modelos:

- **Eufemismo**: nivel 3 escrito de forma contida, sem nenhuma palavra alarmante. E como a
  denuncia grave chega de verdade.
- **Negacao explicita**: "nao houve ameaca nenhuma, mas quero registrar".
- **Distrator**: palavra alarmante em contexto benigno.
- **Ambiguidade real**: o relato que voce mesmo nao consegue classificar. Esse e ouro.

## 3. O que o validador checa

`uv run lab holdout` roda antes de qualquer execucao e recusa o arquivo em erro. As
checagens, na ordem do estrago que cada uma evita:

| Checagem | Gravidade | Por que |
|---|---|---|
| Urgencia gravada bate com `compor_urgencia` | erro | Um nivel digitado a mao faz o arquivo discordar da regra contra a qual tudo o mais e medido |
| Texto identico ou quase a gramatica | erro | Um holdout copiado da gramatica nao detecta vazamento, que e a unica coisa que ele existe para detectar |
| Relato em branco ou com o placeholder | erro | Um modelo nao preenchido nunca pode passar por trabalho escrito |
| Texto repetido entre casos | erro | Peso duplo no mesmo caso, sem ninguem notar |
| Sem autor | erro | Rotulagem de uma pessoa e limitacao declarada; sem nome nao da para medi-la |
| Algo com cara de CPF, CNPJ, telefone, e-mail ou CEP | aviso | O holdout e inventado; se ha PII, ou e falsa e confunde, ou e real e nao podia estar ali |
| Menos de 60 casos, ou menos de 10 num nivel | aviso | Diz o que ainda nao da para publicar |

Erros bloqueiam a execucao. Avisos aparecem e deixam voce decidir.

Uma consequencia proposital: `lab rodar --fonte holdout` **valida antes de comecar**. Uma
execucao que gasta chave e tempo para produzir um numero que ninguem deveria usar e pior que
uma que nao roda.

## 4. Rodar contra o holdout

```bash
uv run lab rodar --fonte holdout --comparar --repeticoes 5 --limite 0
```

`--limite 0` roda o holdout inteiro, que e o certo: ele e pequeno de proposito, e sortear
subconjunto de 60 casos joga fora a unica medida que importa.

## 5. O braco que depende disto

O holdout deixou de ser opcional quando o Laya entrou no catalogo. O numero publicado do
Laya (0,766 em typed-decisions) e **depois de fine-tuning**; zero-shot ele marca 0,352,
abaixo do baseline de classe majoritaria. Uma comparacao honesta precisa do braco afinado —
e afinar na gramatica sintetica e avaliar na gramatica sintetica nao mede nada, porque a
gramatica estaria se avaliando.

Ou seja: **sem holdout, nao ha como dar ao modelo aberto uma comparacao justa.** Ver
[`docs/local.md`](local.md), secao 4.
