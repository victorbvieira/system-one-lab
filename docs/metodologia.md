# Metodologia

> Status: esqueleto. O conteudo entra na Tarefa 3, junto com a gramatica e o
> `dataset.yaml`. Este arquivo existe desde a fundacao porque nenhum numero
> deste repositorio deve circular sem ele.

## O que este documento vai responder

1. **Como os datasets foram feitos.** Gramatica combinatoria deterministica, com
   semente fixa: cenario x flags de gravidade x registro linguistico x slots do
   Faker `pt_BR`. Nenhum LLM escreve dado neste repositorio.
2. **Por que confiar neles.** O rotulo sai das flags, nao do texto, entao ele e
   auditavel e discutivel. Nao e opiniao de ninguem.
3. **Qual ruido foi plantado e por que.** Negacoes, distratores lexicais,
   eufemismo e relato ambiguo. Sem isso o benchmark vira detector de
   palavra-chave e o resultado nao vale nada.
4. **O holdout humano.** 60 casos escritos e rotulados a mao, fora da gramatica.
   A metrica do artigo e a do holdout; a do sintetico serve para iterar rapido.
5. **Distribuicao de classes.** Relatorio de balanceamento do dataset gerado.
6. **O que fazer se o sintetico for muito melhor que o holdout.** Significa que a
   gramatica vazou o rotulo. Isso e um resultado, nao um fracasso.

## Limites, que valem para todo numero publicado

Datasets pequenos, dominio unico, rotulagem de uma pessoa. Isto nao e uma
comparacao definitiva entre modelos.
