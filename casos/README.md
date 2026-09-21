# casos/

Cada subpasta e um caso de decisao tipada, com o mesmo formato:

```
<caso>/
  tipos.py      output_type e rubrica
  gramatica/    templates, slots e regras de rotulo
  gerar.py      gera o dataset sem LLM, com semente fixa
  dataset.yaml  gerado, versionado
  holdout.yaml  escrito e revisado a mao, versionado
  agente.py     o agente Pydantic AI do caso
```

O nome da pasta usa hifen (`canal-de-denuncia`), o que a torna nao importavel
como pacote Python. E proposital: a regra 9.2 do briefing manda usar o nome
generico do dominio, nunca o nome do produto. Os modulos do caso sao carregados
por caminho (`importlib.util.spec_from_file_location`) a partir de `lab/run.py`,
que resolve o caso pelo argumento `--caso`.

Casos previstos: `canal-de-denuncia` (grau de urgencia, primeiro) e
`selecao-de-pauta` (depois).
