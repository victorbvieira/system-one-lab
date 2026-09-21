"""The probability recovery is exact, and a wrong inverse would silently skew calibration."""

from __future__ import annotations

import pytest

from lab.confianca import probabilidade_de_sim, reler_com_limiares


@pytest.mark.parametrize("limiar", [0.5, 0.3, 0.75])
@pytest.mark.parametrize("p", [0.0, 0.05, 0.3, 0.5, 0.62, 0.95, 1.0])
def test_recupera_a_probabilidade_que_o_modelo_respondeu(limiar: float, p: float) -> None:
    """Mirrors Pydantic AI's own rounding, then inverts it: the two must agree."""
    escolhido = p >= limiar
    confianca = (p - limiar) / (1 - limiar) if escolhido else (limiar - p) / limiar
    assert probabilidade_de_sim(escolhido, confianca, limiar) == pytest.approx(p)


def test_limiar_mais_baixo_vira_um_nao_apertado_em_sim() -> None:
    # Answered at 0.5 and rejected with confidence 0.2, so the probability of yes was 0.4:
    # a no under the default bar, a yes under the risk bar of 0.3.
    releitura = reler_com_limiares(
        valores={"risco_fisico_iminente": False, "tem_evidencia": False},
        confiancas={"risco_fisico_iminente": 0.2, "tem_evidencia": 0.9},
        limiar_original=0.5,
        limiar_novo=0.3,
        campos=("risco_fisico_iminente",),
    )
    assert releitura.probabilidades["risco_fisico_iminente"] == pytest.approx(0.4)
    assert releitura.valores == {"risco_fisico_iminente": True}
    assert releitura.mudaram == ("risco_fisico_iminente",)
    # A field outside the risk list keeps its answer, and still gets its probability read.
    assert releitura.probabilidades["tem_evidencia"] == pytest.approx(0.05)
