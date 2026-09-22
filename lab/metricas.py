"""The metrics that go into the article, and the evaluators that produce them.

Two layers. The evaluators are Pydantic Evals ones, scored per case while a run happens.
The aggregate functions read a finished run's cases and produce the numbers the report and
the dashboard show.

What is deliberately not here: a single "accuracy". The headline metric of this case is
recall of level 3, because a false negative there is what makes a triage unusable, and an
average over four levels hides exactly that.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from lab.custo import Custo, por_mil
from lab.resultados import ResultadoDeCaso

__all__ = [
    "AcertoDeSinal",
    "CapturouNivel3",
    "UrgenciaComposta",
    "agregar",
    "erro_de_calibracao",
    "percentil",
]


def _saida(ctx: EvaluatorContext[Any, Any, Any]) -> dict[str, Any]:
    """What the task returned, which is where a run's answer lives.

    Not ``ctx.attributes``: those are what a task explicitly records on the side, and
    reading them here judged every signal wrong while reporting a clean run.
    """
    return ctx.output if isinstance(ctx.output, dict) else {}


SINAIS = (
    "risco_fisico_iminente",
    "em_andamento",
    "retaliacao",
    "hierarquia_do_acusado",
    "afetados",
    "tem_evidencia",
)


# -- evaluators, scored while the run happens ------------------------------------------


@dataclass
class CapturouNivel3(Evaluator[Any, Any, Any]):
    """Did the model catch a level 3? The one assertion that decides usability.

    Only cases actually labelled 3 are judged; everything else is left unscored rather
    than counted as a pass, which would dilute the number that matters.
    """

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> dict[str, bool]:
        esperado = (ctx.metadata or {}).get("urgencia")
        if esperado != 3:
            return {}
        return {"capturou_nivel_3": _saida(ctx).get("urgencia_composta") == 3}


@dataclass
class UrgenciaComposta(Evaluator[Any, Any, Any]):
    """Whether the level composed from the signals matches the label."""

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> dict[str, bool]:
        esperado = (ctx.metadata or {}).get("urgencia")
        if esperado is None:
            return {}
        return {"urgencia_composta": _saida(ctx).get("urgencia_composta") == esperado}


@dataclass
class AcertoDeSinal(Evaluator[Any, Any, Any]):
    """One assertion per signal, so a mistake points at the field that caused it."""

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> dict[str, bool]:
        esperados = (ctx.metadata or {}).get("sinais") or {}
        ambiguos = set((ctx.metadata or {}).get("sinais_ambiguos") or [])
        obtidos = _saida(ctx).get("sinais") or {}
        return {
            f"sinal_{nome}": obtidos.get(nome) == valor
            for nome, valor in esperados.items()
            if nome not in ambiguos
        }


# -- aggregates, read from a finished run ----------------------------------------------


def percentil(valores: Sequence[float], p: float) -> float:
    """The p-th percentile by nearest rank, which needs no interpolation to explain."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    indice = max(0, min(len(ordenados) - 1, round(p / 100 * len(ordenados) + 0.5) - 1))
    return ordenados[indice]


def erro_de_calibracao(
    pares: Sequence[tuple[float, bool]], faixas: int = 10
) -> dict[str, Any] | None:
    """Expected calibration error over (confidence, was it right) pairs.

    Confidence is binned, and each bin contributes the gap between how sure the model said
    it was and how often it was right, weighted by how many predictions fell in it. A model
    that is confident and wrong scores worse than one that is unsure and wrong, which is
    the ordering that matters when the answer routes a decision.

    Returns:
        The error, the per-bin detail for plotting a reliability curve, and the mean
        confidence on right and wrong answers. ``None`` when the model reports no
        confidence at all - which is itself a finding, not a zero.
    """
    if not pares:
        return None

    largura = 1 / faixas
    detalhe: list[dict[str, Any]] = []
    erro = 0.0
    for indice in range(faixas):
        inferior, superior = indice * largura, (indice + 1) * largura
        na_faixa = [
            (c, ok)
            for c, ok in pares
            if inferior <= c < superior or (indice == faixas - 1 and c == 1.0)
        ]
        if not na_faixa:
            detalhe.append({"faixa": round(inferior, 2), "n": 0, "confianca": None, "acerto": None})
            continue
        confianca = statistics.fmean(c for c, _ in na_faixa)
        acerto = statistics.fmean(1.0 if ok else 0.0 for _, ok in na_faixa)
        erro += len(na_faixa) / len(pares) * abs(acerto - confianca)
        detalhe.append(
            {
                "faixa": round(inferior, 2),
                "n": len(na_faixa),
                "confianca": round(confianca, 4),
                "acerto": round(acerto, 4),
            }
        )

    certos = [c for c, ok in pares if ok]
    errados = [c for c, ok in pares if not ok]
    return {
        "erro": round(erro, 4),
        "faixas": detalhe,
        "confianca_media_quando_acerta": round(statistics.fmean(certos), 4) if certos else None,
        "confianca_media_quando_erra": round(statistics.fmean(errados), 4) if errados else None,
        "previsoes": len(pares),
    }


def _matriz(casos: Sequence[ResultadoDeCaso]) -> dict[str, dict[str, int]]:
    matriz: dict[str, dict[str, int]] = {}
    for caso in casos:
        esperado = (
            "indeterminado" if caso.urgencia_esperada is None else str(caso.urgencia_esperada)
        )
        obtido = "indeterminado" if caso.urgencia_composta is None else str(caso.urgencia_composta)
        matriz.setdefault(esperado, {})
        matriz[esperado][obtido] = matriz[esperado].get(obtido, 0) + 1
    return matriz


def _dispersao(casos: Sequence[ResultadoDeCaso], chave: str) -> dict[str, Any]:
    """Spread of a metric across repetitions. Without it, noise is published as difference."""
    por_repeticao: dict[int, list[ResultadoDeCaso]] = {}
    for caso in casos:
        por_repeticao.setdefault(caso.repeticao, []).append(caso)
    valores = []
    for grupo in por_repeticao.values():
        relevantes = [c for c in grupo if c.urgencia_esperada == 3]
        if chave == "recall_nivel_3" and relevantes:
            valores.append(sum(1 for c in relevantes if c.urgencia_composta == 3) / len(relevantes))
        elif chave == "acuracia_composta":
            decididos = [c for c in grupo if c.urgencia_esperada is not None]
            if decididos:
                valores.append(
                    sum(1 for c in decididos if c.urgencia_composta == c.urgencia_esperada)
                    / len(decididos)
                )
    if len(valores) < 2:
        return {
            "repeticoes": len(valores),
            "media": valores[0] if valores else None,
            "desvio": None,
        }
    return {
        "repeticoes": len(valores),
        "media": round(statistics.fmean(valores), 4),
        "desvio": round(statistics.stdev(valores), 4),
        "min": round(min(valores), 4),
        "max": round(max(valores), 4),
    }


def agregar(
    casos: Sequence[ResultadoDeCaso], custo: Custo, segundos_de_parede: float | None = None
) -> dict[str, Any]:
    """Every published metric for one run.

    Args:
        casos: Every case result, across every repetition.
        custo: The run's total cost.
        segundos_de_parede: Wall clock of the evaluation. It is what decides throughput,
            and throughput is what a machine-priced model's cost hangs on.

    Returns:
        The metrics dictionary written into the result file and read by the dashboard.
    """
    validos = [c for c in casos if c.erro is None]
    decididos = [c for c in validos if c.urgencia_esperada is not None]
    nivel_3 = [c for c in decididos if c.urgencia_esperada == 3]
    disse_3 = [c for c in decididos if c.urgencia_composta == 3]
    capturados = [c for c in nivel_3 if c.urgencia_composta == 3]
    abstencao = [c for c in validos if c.urgencia_esperada is None]

    recall = len(capturados) / len(nivel_3) if nivel_3 else None
    precisao = len(capturados) / len(disse_3) if disse_3 else None
    usd_por_mil, brl_por_mil = por_mil(custo, len(validos))

    pares_de_calibracao = [
        (
            caso.confianca[nome],
            caso.obtido.get(nome) == (caso.esperado.get("sinais") or {}).get(nome),
        )
        for caso in validos
        for nome in SINAIS
        if nome in caso.confianca and nome not in (caso.esperado.get("sinais_ambiguos") or [])
    ]

    por_sinal = {}
    for nome in SINAIS:
        julgados = [c for c in validos if nome in c.acertos]
        if julgados:
            por_sinal[nome] = round(sum(1 for c in julgados if c.acertos[nome]) / len(julgados), 4)

    mudou_com_limiar = [c for c in validos if c.releitura_de_risco.get("mudaram")]
    capturados_com_limiar = [
        c
        for c in nivel_3
        if c.releitura_de_risco.get("urgencia_composta", c.urgencia_composta) == 3
    ]

    return {
        "casos_avaliados": len(validos),
        "casos_com_erro": len(casos) - len(validos),
        "recall_nivel_3": _arredondar(recall),
        "precisao_nivel_3": _arredondar(precisao),
        "recall_nivel_3_com_limiar_de_risco": _arredondar(
            len(capturados_com_limiar) / len(nivel_3) if nivel_3 else None
        ),
        "casos_que_o_limiar_de_risco_mudou": len(mudou_com_limiar),
        "acuracia_composta": _arredondar(
            sum(1 for c in decididos if c.urgencia_composta == c.urgencia_esperada) / len(decididos)
            if decididos
            else None
        ),
        "acuracia_direta": _arredondar(
            sum(1 for c in decididos if c.urgencia_direta == c.urgencia_esperada) / len(decididos)
            if decididos
            else None
        ),
        "acuracia_por_sinal": por_sinal,
        "abstencao": {
            "casos": len(abstencao),
            "abstiveram": sum(1 for c in abstencao if c.urgencia_composta is None),
            "taxa": _arredondar(
                sum(1 for c in abstencao if c.urgencia_composta is None) / len(abstencao)
                if abstencao
                else None
            ),
            "falsa_abstencao": sum(1 for c in decididos if c.urgencia_composta is None),
        },
        "matriz_de_confusao": _matriz(validos),
        "custo_usd": round(custo.dolares, 6),
        "custo_brl": round(custo.reais, 6),
        "custo_usd_por_mil": round(usd_por_mil, 4),
        "custo_brl_por_mil": round(brl_por_mil, 4),
        "custo_usd_por_nivel_3_detectado": (
            round(custo.dolares / len(capturados), 6) if capturados else None
        ),
        "tokens_de_entrada": custo.tokens_de_entrada,
        "tokens_de_saida": custo.tokens_de_saida,
        "triagens_por_hora": (
            round(len(validos) / segundos_de_parede * 3600, 1) if segundos_de_parede else None
        ),
        "segundos_de_parede": None if segundos_de_parede is None else round(segundos_de_parede, 2),
        "latencia_p50_ms": round(percentil([c.latencia_ms for c in validos], 50), 1),
        "latencia_p95_ms": round(percentil([c.latencia_ms for c in validos], 95), 1),
        "requisicoes_por_decisao": _arredondar(
            sum(c.requisicoes for c in validos) / len(validos) if validos else None
        ),
        "taxa_de_handoff": _arredondar(
            sum(1 for c in validos if c.handoff) / len(validos) if validos else None
        ),
        "erro_de_calibracao": (
            calibracao["erro"] if (calibracao := erro_de_calibracao(pares_de_calibracao)) else None
        ),
        "calibracao": calibracao,
        "dispersao": {
            "recall_nivel_3": _dispersao(validos, "recall_nivel_3"),
            "acuracia_composta": _dispersao(validos, "acuracia_composta"),
        },
    }


def _arredondar(valor: float | None, casas: int = 4) -> float | None:
    return None if valor is None else round(valor, casas)
