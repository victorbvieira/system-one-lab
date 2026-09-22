"""Cost from token usage and a fixed price table.

Cost on its own says nothing - a model that is cheap and misses the level 3 reports costs
more than the expensive one. What is computed here feeds the metric that does mean
something: dollars per level 3 correctly detected.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab.precos import TabelaDePrecos

__all__ = ["Custo", "custo_de_maquina", "custo_de_uso", "por_mil"]


@dataclass(frozen=True)
class Custo:
    """What one request, or one run, cost."""

    dolares: float
    reais: float
    tokens_de_entrada: int
    tokens_de_saida: int

    def __add__(self, outro: Custo) -> Custo:
        return Custo(
            dolares=self.dolares + outro.dolares,
            reais=self.reais + outro.reais,
            tokens_de_entrada=self.tokens_de_entrada + outro.tokens_de_entrada,
            tokens_de_saida=self.tokens_de_saida + outro.tokens_de_saida,
        )

    @classmethod
    def zero(cls) -> Custo:
        return cls(0.0, 0.0, 0, 0)


def custo_de_uso(
    tokens_de_entrada: int,
    tokens_de_saida: int,
    id_de_preco: str,
    tabela: TabelaDePrecos,
) -> Custo:
    """Price one request's usage against a fixed table.

    Args:
        tokens_de_entrada: Input tokens the provider reported.
        tokens_de_saida: Output tokens the provider reported.
        id_de_preco: The model's key in the price table.
        tabela: The dated table. Never a live lookup.

    Returns:
        The cost, in dollars and in reais at the rate recorded with the prices.
    """
    preco = tabela.de(id_de_preco)
    dolares = preco.custo(tokens_de_entrada, tokens_de_saida)
    return Custo(
        dolares=dolares,
        reais=tabela.em_reais(dolares),
        tokens_de_entrada=tokens_de_entrada,
        tokens_de_saida=tokens_de_saida,
    )


def custo_de_maquina(segundos: float, nome_da_maquina: str, tabela: TabelaDePrecos) -> Custo:
    """Price a stretch of wall clock against a machine's hourly rate.

    This is the cost of a model that runs on your own hardware, and it is a different kind
    of number from the one above. Token cost scales with what you use; machine cost scales
    with how long you hold the machine, so the same model is cheap saturated and ruinous
    idle. The wall clock of a run is the honest denominator for a benchmark: it prices the
    machine for exactly the time it was working.

    Args:
        segundos: Wall clock of the run - not the sum of the per-case latencies, which
            counts each concurrent worker separately and would multiply the bill.
        nome_da_maquina: A key of the ``maquinas`` section of the price files.
        tabela: The dated table.

    Returns:
        The cost, with zero tokens: a local model spends no tokens anywhere.
    """
    maquina = tabela.maquina(nome_da_maquina)
    dolares = maquina.custo(segundos)
    return Custo(
        dolares=dolares,
        reais=tabela.em_reais(dolares),
        tokens_de_entrada=0,
        tokens_de_saida=0,
    )


def por_mil(custo: Custo, decisoes: int) -> tuple[float, float]:
    """Scale a total to a thousand decisions, which is the unit the article uses.

    Returns:
        Dollars and reais per thousand triaged reports. ``(0, 0)`` for no decisions, since
        a rate over nothing is not an infinity worth propagating.
    """
    if decisoes <= 0:
        return 0.0, 0.0
    fator = 1000 / decisoes
    return custo.dolares * fator, custo.reais * fator
