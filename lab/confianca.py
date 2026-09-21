"""Recover what a System One answer knew, and apply an asymmetric bar to it.

Jev answers a yes/no with the probability of yes, and Pydantic AI rounds it at a bar,
reporting how far from the bar it landed as the field's confidence. The probability itself
is not in the response - but it is recoverable exactly, because the scaling is invertible:

    chosen:      p = bar + confidence * (1 - bar)
    not chosen:  p = bar * (1 - confidence)

That matters twice. It is what makes calibration measurable on boolean fields, and it is
what lets a lower bar be applied to the fields where a false negative is the expensive
mistake, in post-processing, without paying for a second request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["Releitura", "probabilidade_de_sim", "reler_com_limiares"]


def probabilidade_de_sim(escolhido: bool, confianca: float, limiar: float) -> float:
    """The model's probability of yes, from the answer and the bar it was rounded at.

    Args:
        escolhido: The boolean as returned.
        confianca: The confidence reported for that field.
        limiar: The bar the answer was measured against.

    Returns:
        The probability of yes, clamped to 0..1.
    """
    bruta = limiar + confianca * (1 - limiar) if escolhido else limiar * (1 - confianca)
    return min(max(bruta, 0.0), 1.0)


@dataclass(frozen=True)
class Releitura:
    """A set of boolean answers reread against a different bar."""

    valores: dict[str, bool]
    """The fields after the new bar, only for those the new bar was applied to."""

    probabilidades: dict[str, float]
    """The recovered probability of yes per boolean field."""

    mudaram: tuple[str, ...]
    """Fields the new bar flipped. Worth reporting: it is the asymmetry doing its job."""


def reler_com_limiares(
    valores: Mapping[str, Any],
    confiancas: Mapping[str, float],
    limiar_original: float,
    limiar_novo: float,
    campos: tuple[str, ...],
) -> Releitura:
    """Reread boolean fields against a second bar.

    Args:
        valores: The output's fields, as returned.
        confiancas: ``provider_details['confidence']``.
        limiar_original: The bar the request was answered at.
        limiar_novo: The bar to apply to ``campos``.
        campos: The fields the new bar applies to, typically the risk ones.

    Returns:
        The reread values, the recovered probabilities for every boolean, and which fields
        changed.
    """
    probabilidades: dict[str, float] = {}
    for nome, valor in valores.items():
        if isinstance(valor, bool) and nome in confiancas:
            probabilidades[nome] = probabilidade_de_sim(
                valor, confiancas[nome], limiar_original
            )

    relidos: dict[str, bool] = {}
    mudaram: list[str] = []
    for nome in campos:
        if nome not in probabilidades:
            continue
        novo = probabilidades[nome] >= limiar_novo
        relidos[nome] = novo
        if novo != bool(valores[nome]):
            mudaram.append(nome)
    return Releitura(valores=relidos, probabilidades=probabilidades, mudaram=tuple(mudaram))
