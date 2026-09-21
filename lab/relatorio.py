"""Printing a run, and comparing runs against each other.

Everything printed here carries the four things a published number needs: the pinned model
version, the price file, the dataset size and the number of repetitions. They are in the
header of every table on purpose - a number copied out of a terminal loses its footnotes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.table import Table

from lab.resultados import Execucao

__all__ = ["comparar", "imprimir", "linha_de_procedencia"]

_COLUNAS = (
    ("recall_nivel_3", "Recall nivel 3"),
    ("precisao_nivel_3", "Precisao nivel 3"),
    ("acuracia_composta", "Acuracia composta"),
    ("acuracia_direta", "Acuracia direta"),
    ("custo_usd_por_mil", "US$/mil"),
    ("custo_brl_por_mil", "R$/mil"),
    ("custo_usd_por_nivel_3_detectado", "US$/nivel 3"),
    ("latencia_p50_ms", "p50 ms"),
    ("latencia_p95_ms", "p95 ms"),
    ("requisicoes_por_decisao", "Req/decisao"),
    ("taxa_de_handoff", "Hand-off"),
    ("erro_de_calibracao", "Erro de calibracao"),
)


def linha_de_procedencia(execucao: Execucao) -> str:
    """The sentence that has to travel with every number this run produced."""
    return (
        f"{execucao.modelo_id} (respondeu {execucao.modelo_versao_reportada}) | "
        f"precos {', '.join(execucao.precos['arquivos'])} de "
        f"{', '.join(execucao.precos['coletado_em'])} | "
        f"{execucao.dataset['selecionados']} casos de {execucao.dataset['arquivo']} "
        f"(semente {execucao.dataset['semente']}) | {execucao.repeticoes} repeticoes"
    )


def imprimir(execucao: Execucao, console: Console | None = None) -> None:
    """Print one run: provenance, headline metrics, per-signal accuracy, confusion matrix."""
    console = console or Console()
    metricas = execucao.metricas

    console.print(f"\n[bold]{execucao.id}[/bold]  {execucao.caso} / {execucao.modelo}")
    console.print(f"[dim]{linha_de_procedencia(execucao)}[/dim]\n")

    principal = Table(title="Metricas", show_header=True)
    principal.add_column("Metrica")
    principal.add_column("Valor", justify="right")
    for chave, rotulo in _COLUNAS:
        principal.add_row(rotulo, _formatar(metricas.get(chave)))
    dispersao = metricas.get("dispersao", {}).get("recall_nivel_3", {})
    if dispersao.get("desvio") is not None:
        principal.add_row(
            "Recall nivel 3 (dispersao)",
            f"{dispersao['media']} +/- {dispersao['desvio']} "
            f"em {dispersao['repeticoes']} repeticoes",
        )
    console.print(principal)

    if por_sinal := metricas.get("acuracia_por_sinal"):
        tabela = Table(title="Acuracia por sinal")
        tabela.add_column("Sinal")
        tabela.add_column("Acuracia", justify="right")
        for nome, valor in sorted(por_sinal.items(), key=lambda item: item[1]):
            tabela.add_row(nome, _formatar(valor))
        console.print(tabela)

    if matriz := metricas.get("matriz_de_confusao"):
        console.print(_tabela_de_confusao(matriz))

    abstencao = metricas.get("abstencao", {})
    if abstencao.get("casos"):
        console.print(
            f"Abstencao: {abstencao['abstiveram']}/{abstencao['casos']} casos indeterminados "
            f"foram abstidos; {abstencao['falsa_abstencao']} abstencoes indevidas."
        )
    if metricas.get("casos_com_erro"):
        console.print(f"[red]{metricas['casos_com_erro']} casos falharam.[/red]")


def _tabela_de_confusao(matriz: dict[str, dict[str, int]]) -> Table:
    colunas = sorted({obtido for linha in matriz.values() for obtido in linha}, key=_ordem)
    tabela = Table(title="Matriz de confusao (linha: esperado, coluna: obtido)")
    tabela.add_column("esperado \\ obtido")
    for coluna in colunas:
        tabela.add_column(coluna, justify="right")
    for esperado in sorted(matriz, key=_ordem):
        tabela.add_row(esperado, *[str(matriz[esperado].get(c, 0)) for c in colunas])
    return tabela


def _ordem(rotulo: str) -> tuple[int, str]:
    return (1, rotulo) if rotulo == "indeterminado" else (0, rotulo)


def comparar(execucoes: Sequence[Execucao], console: Console | None = None) -> None:
    """Put several runs side by side, one column per model."""
    console = console or Console()
    if not execucoes:
        console.print("Nada para comparar.")
        return

    tabela = Table(title=f"Comparacao: {execucoes[0].caso}", show_header=True)
    tabela.add_column("Metrica")
    for execucao in execucoes:
        tabela.add_column(execucao.modelo, justify="right")

    for chave, rotulo in _COLUNAS:
        valores = [e.metricas.get(chave) for e in execucoes]
        melhor = _melhor(chave, valores)
        celulas = [
            f"[bold green]{_formatar(v)}[/bold green]" if i == melhor else _formatar(v)
            for i, v in enumerate(valores)
        ]
        tabela.add_row(rotulo, *celulas)
    console.print(tabela)

    console.print("\n[dim]Procedencia de cada coluna:[/dim]")
    for execucao in execucoes:
        console.print(f"[dim]  {execucao.modelo}: {linha_de_procedencia(execucao)}[/dim]")


_MENOR_E_MELHOR = {
    "custo_usd_por_mil",
    "custo_brl_por_mil",
    "custo_usd_por_nivel_3_detectado",
    "latencia_p50_ms",
    "latencia_p95_ms",
    "requisicoes_por_decisao",
    "taxa_de_handoff",
    "erro_de_calibracao",
}


def _melhor(chave: str, valores: Sequence[Any]) -> int | None:
    """Which column wins this row, or ``None`` when nothing comparable was reported."""
    numericos = [(i, v) for i, v in enumerate(valores) if isinstance(v, int | float)]
    if len(numericos) < 2:
        return None
    escolher = min if chave in _MENOR_E_MELHOR else max
    return escolher(numericos, key=lambda item: item[1])[0]


def _formatar(valor: Any) -> str:
    if valor is None:
        return "[dim]nao reportado[/dim]"
    if isinstance(valor, float):
        return f"{valor:.4f}".rstrip("0").rstrip(".") if abs(valor) < 100 else f"{valor:.1f}"
    return str(valor)
