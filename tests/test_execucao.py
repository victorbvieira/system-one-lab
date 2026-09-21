"""End-to-end run against a simulated model, so the pipeline is proven without a key.

The fake answers the way the System One route does - a filled output tool plus per-field
confidence in ``provider_details`` - which is what exercises the probability recovery, the
asymmetric risk bar and the metrics in one pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from lab.casos import carregar_caso
from lab.execucao import Plano, executar, selecionar
from lab.resultados import carregar_execucao, escrever_execucao

CASO = carregar_caso("canal-de-denuncia")


def _resposta_falsa(
    sinais: dict[str, Any], confianca: dict[str, float]
) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    def responder(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nome = info.output_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(nome, sinais)],
            model_name="jev-1.13.0",
            provider_name="typesafe",
            provider_details={"confidence": confianca, "probabilities": {}, "scores": {}},
            finish_reason="tool_call",
        )

    return responder


SINAIS_DE_TESTE = {
    "risco_fisico_iminente": False,
    "em_andamento": True,
    "retaliacao": False,
    "hierarquia_do_acusado": "gestor_direto",
    "afetados": "um_time",
    "tem_evidencia": True,
    "urgencia_direta": 2,
}
# risco_fisico_iminente answered no with confidence 0.2 at a bar of 0.5 means a probability
# of yes of 0.4: a no by default, a yes under the risk bar of 0.3.
CONFIANCA_DE_TESTE = {
    "risco_fisico_iminente": 0.2,
    "em_andamento": 0.9,
    "retaliacao": 0.8,
    "hierarquia_do_acusado": 0.7,
    "afetados": 0.6,
    "tem_evidencia": 0.95,
    "urgencia_direta": 0.5,
}


@pytest.fixture
def plano(monkeypatch: pytest.MonkeyPatch) -> Plano:
    agente = CASO.modulo("agente")
    monkeypatch.setattr(
        agente,
        "construir",
        lambda *a, **k: FunctionModel(_resposta_falsa(SINAIS_DE_TESTE, CONFIANCA_DE_TESTE)),
    )
    return Plano(modelo="jev", limite=8, repeticoes=2, tracos="amostra", amostra_de_tracos=2)


def test_amostra_mantem_o_balanceamento_de_classes() -> None:
    from lab.execucao import carregar_dataset

    documento = carregar_dataset("canal-de-denuncia")
    escolhidos = selecionar(documento, Plano(limite=10))
    niveis = {c["rotulo"]["urgencia"] for c in escolhidos}
    assert niveis == {0, 1, 2, 3, None}, "a amostra perdeu um nivel"


@pytest.mark.anyio
async def test_execucao_completa_produz_metricas_e_traco(plano: Plano) -> None:
    execucao = await executar(plano)

    assert len(execucao.casos) == 16, "8 casos x 2 repeticoes"
    # The version recorded is the one the provider reported for the request, not the one
    # asked for: with a real key that is "jev-1.13.0", and here it is the fake's own name.
    # Recording what answered, rather than what was requested, is the point.
    assert execucao.modelo_versao_reportada
    assert execucao.modelo_id == "jev-1.13.0"
    assert execucao.dataset["semente"] == 20260921
    assert execucao.precos["arquivos"]

    metricas = execucao.metricas
    assert metricas["casos_avaliados"] == 16
    assert metricas["custo_usd"] > 0
    assert metricas["latencia_p50_ms"] >= 0
    assert metricas["erro_de_calibracao"] is not None

    # O limiar de risco reabre o campo respondido com probabilidade 0.4.
    relido = next(c for c in execucao.casos if c.releitura_de_risco)
    assert "risco_fisico_iminente" in relido.releitura_de_risco["mudaram"]
    assert relido.releitura_de_risco["urgencia_composta"] == 3
    assert relido.probabilidades_booleanas["risco_fisico_iminente"] == pytest.approx(0.4)

    # O traco e guardado so para a amostra pedida.
    com_traco = [c for c in execucao.casos if c.traco is not None]
    assert len(com_traco) == 2
    primeiro = com_traco[0].traco
    assert primeiro is not None and primeiro["passos"], "o traco tem de conter os passos"


@pytest.mark.anyio
async def test_resultado_vai_e_volta_do_disco(
    plano: Plano, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lab.resultados as resultados

    monkeypatch.setattr(resultados, "raiz_dos_resultados", lambda: tmp_path)
    execucao = await executar(plano)
    destino = escrever_execucao(execucao)

    assert destino.exists()
    de_volta = carregar_execucao(destino)
    assert de_volta.metricas == execucao.metricas
    assert len(de_volta.casos) == len(execucao.casos)

    historico = (tmp_path / "history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(historico[-1])["modelo"] == "jev"


SINAIS_COM_UM_ERRO = {**SINAIS_DE_TESTE, "tem_evidencia": False}


@pytest.mark.anyio
async def test_acuracia_por_sinal_aponta_o_campo_errado(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deliberate mistake on one signal has to show up on that signal, and only there.

    This caught a real bug: the evaluators were reading ``ctx.attributes`` instead of the
    task's output, so every signal scored as wrong while the run reported clean. A metric
    that fails silently is worse than one that raises.
    """
    agente = CASO.modulo("agente")
    monkeypatch.setattr(
        agente,
        "construir",
        lambda *a, **k: FunctionModel(_resposta_falsa(SINAIS_COM_UM_ERRO, CONFIANCA_DE_TESTE)),
    )
    execucao = await executar(Plano(modelo="jev", limite=8, repeticoes=1, tracos="nenhum"))

    por_sinal = execucao.metricas["acuracia_por_sinal"]
    assert set(por_sinal) == {
        "risco_fisico_iminente",
        "em_andamento",
        "retaliacao",
        "hierarquia_do_acusado",
        "afetados",
        "tem_evidencia",
    }
    # Every case answered `tem_evidencia=False`; the corpus has cases labelled both ways,
    # so this signal cannot be perfect while another that never varies could be.
    assert por_sinal["tem_evidencia"] < 1.0
    assert execucao.metricas["calibracao"]["previsoes"] > 0
