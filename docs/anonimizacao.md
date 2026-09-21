# Anonimizacao

> Status: esqueleto. O conteudo entra na Tarefa 2, junto com o pacote
> `anonimizador/`.

## Aviso que vem antes de tudo

**Anonimizacao automatica nao e garantia.** NER erra, sobretudo em nome
incomum. Para dado real saindo do perimetro, isso e decisao de compliance com
revisao humana, nao um `pip install`. No repositorio publico so entra dado
sintetico.

## Duas coisas diferentes, que nao se confundem

- O dataset deste repositorio e **sintetico**: nao ha PII real para anonimizar.
- O anonimizador existe para o pipeline que um dia vai ler relato real, e para
  ser testado contra a PII que a gramatica planta de proposito.

## O que este documento vai detalhar

1. **Camada 1, deterministica.** Regex mais validacao de digito verificador:
   CPF, CNPJ, telefone brasileiro, e-mail, CEP, placa Mercosul e antiga, chave
   PIX aleatoria, RG, matricula, cartao com Luhn, IP, URL. Validar o digito em
   vez de so casar o padrao derruba o falso positivo.
2. **Camada 2, nomes proprios.** Gazetteer (censo do IBGE) como base auditavel,
   NER estatistico (`spaCy`, `pt_core_news_lg`) para o que a lista nao pega, e
   Presidio por cima se quiser orquestracao pronta. Nenhuma das tres e LLM.
3. **Substituicao consistente.** Nao apagar, substituir por pseudonimo estavel:
   `pseudonimo(nome) = FAKER_POOL[HMAC_SHA256(salt, normaliza(nome)) mod len(POOL)]`.
   Salt **por documento** e o padrao correto para canal de denuncia; salt global
   so com decisao explicita. O salt nunca entra no repositorio.
4. **Canarios.** PII conhecida em posicao conhecida. O teste de CI falha se o
   recall nao for 100%. A metrica e recall, nao precisao: deixar passar um CPF e
   grave, esconder uma palavra a mais nao e.
