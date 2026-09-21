# resultados/

Versionado de proposito: qualquer pessoa le os numeros sem ter chave de API.

```
resultados/<caso>/<modelo>/<execucao>.json   uma execucao completa
resultados/history.jsonl                     uma linha por execucao, para serie historica
```

Todo arquivo aqui declara, no proprio JSON: versao exata do modelo, arquivo de
preco usado, tamanho do dataset, numero de repeticoes e a semente. Numero sem
essas quatro coisas nao vai para artigo.
