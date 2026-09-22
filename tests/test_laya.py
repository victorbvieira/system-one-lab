"""The local route, tested without weights.

Two things are checked here. First, that the adapter builds the questions with Pydantic
AI's own mapper and reads the answers back through its own reader - that is what keeps the
Jev run and the Laya run asking the same thing, and a drift there would look like a
difference between models. Second, that the contract with those private functions still
holds, so a Pydantic AI upgrade fails here rather than silently changing what is measured.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent

from lab import laya as rota_local
from lab.casos import carregar_caso

CASO = carregar_caso("canal-de-denuncia")
tipos = CASO.modulo("tipos")

RELATO = (
    "Meu gestor direto vem cobrando o time em publico desde marco, e na semana passada "
    "empurrou uma colega contra a parede. Tenho print das mensagens."
)


class AgenteFalso:
    """Answers whatever it is asked, recording the questions it received."""

    def __init__(self) -> None:
        self.perguntas: dict[str, Any] = {}

    def predict(self, estado: Any, perguntas: dict[str, Any]) -> dict[str, Any]:
        self.perguntas = perguntas
        self.estado = estado
        respostas: dict[str, Any] = {}
        for nome, pergunta in perguntas.items():
            if pergunta["type"] == "noul":
                respostas[nome] = {"type": "noul", "noul": 0.9, "confidence": 0.9}
            elif pergunta["type"] == "choice":
                opcoes = list(pergunta["criteria"])
                probabilidade = 1 / len(opcoes)
                respostas[nome] = {
                    "type": "choice",
                    "choice": opcoes[0],
                    "confidence": 0.42,
                    "probabilities": dict.fromkeys(opcoes, probabilidade),
                }
            else:
                niveis = pergunta["criteria"]
                respostas[nome] = {
                    "type": "score",
                    "score": 2.2,
                    "confidence": 0.61,
                    "legend": {str(i): c for i, c in enumerate(niveis)},
                    "probabilities": {str(i): 1 / len(niveis) for i in range(len(niveis))},
                }
        return {
            "model": "laya-rl-agent",
            "answers": respostas,
            "usage": {"input_tokens": 605, "output_tokens": 0},
        }


@pytest.fixture
def agente_falso(monkeypatch: pytest.MonkeyPatch) -> AgenteFalso:
    falso = AgenteFalso()
    monkeypatch.setattr(rota_local, "carregar_agente", lambda *a, **k: falso)
    return falso


@pytest.mark.anyio
async def test_preenche_o_tipo_de_saida_e_reporta_confianca(agente_falso: AgenteFalso) -> None:
    agente = Agent(
        rota_local.ModeloLaya("multilingual"),
        output_type=tipos.Triagem,
        instructions="Triagem de canal de denuncia.",
    )
    resultado = await agente.run(RELATO)

    saida = resultado.output
    assert isinstance(saida, tipos.Triagem)
    assert saida.risco_fisico_iminente is True  # noul de 0.9 acima do limiar padrao
    assert saida.urgencia_direta is tipos.Urgencia.GRAVE  # score 2.2 arredonda para 2

    from pydantic_ai.messages import ModelResponse

    resposta = next(m for m in reversed(resultado.all_messages()) if isinstance(m, ModelResponse))
    detalhes = resposta.provider_details or {}
    assert detalhes["confidence"]["hierarquia_do_acusado"] == pytest.approx(0.42)
    assert detalhes["probabilities"]["afetados"]
    assert detalhes["scores"]["urgencia_direta"] == pytest.approx(2.2)
    assert detalhes["checkpoint"] == "multilingual"


@pytest.mark.anyio
async def test_as_perguntas_sao_as_que_o_pydantic_ai_monta(agente_falso: AgenteFalso) -> None:
    """The six signals become six questions of the right primitive, plus the rubric.

    If this drifts, the Laya run and the Jev run stop being comparable.
    """
    agente = Agent(
        rota_local.ModeloLaya("multilingual"),
        output_type=tipos.Triagem,
        instructions="Triagem de canal de denuncia.",
    )
    await agente.run(RELATO)

    perguntas = agente_falso.perguntas
    tipos_por_campo = {nome: p["type"] for nome, p in perguntas.items()}
    assert tipos_por_campo == {
        "risco_fisico_iminente": "noul",
        "em_andamento": "noul",
        "retaliacao": "noul",
        "tem_evidencia": "noul",
        "hierarquia_do_acusado": "choice",
        "afetados": "choice",
        "urgencia_direta": "score",
    }
    # A rubrica chega como lista ordenada de niveis descritos, que e o que o Laya espera;
    # sem descricao por nivel, nenhuma das duas rotas aceita a pergunta.
    niveis = perguntas["urgencia_direta"]["criteria"]
    assert len(niveis) == 4
    assert all(isinstance(nivel, str) and nivel for nivel in niveis)
    # As opcoes de escolha chegam descritas, nao como nomes nus.
    assert perguntas["hierarquia_do_acusado"]["criteria"]["gestor_direto"]
    # O relato e o estado; a pergunta nao entra no texto julgado.
    assert RELATO in str(agente_falso.estado)


@pytest.mark.anyio
async def test_limiar_booleano_vale_para_a_rota_local(agente_falso: AgenteFalso) -> None:
    """The same bar, doing the same job, read from the same setting as the Jev route."""
    from pydantic_ai.models.typesafe import TypeSafeModelSettings

    agente = Agent(
        rota_local.ModeloLaya(
            "multilingual", settings=TypeSafeModelSettings(typesafe_boolean_threshold=0.95)
        ),
        output_type=tipos.Triagem,
        instructions="Triagem de canal de denuncia.",
    )
    resultado = await agente.run(RELATO)
    # 0.9 passava no limiar padrao de 0.5 e nao passa num de 0.95.
    assert resultado.output.risco_fisico_iminente is False


def test_contrato_com_os_ajudantes_privados_do_pydantic_ai() -> None:
    """These names are private. If an upgrade moves them, fail here and not in a run."""
    from pydantic_ai.models import typesafe

    for nome in ("_fields", "_questions", "_answers", "_map_messages", "_output_tools"):
        assert callable(getattr(typesafe, nome)), nome
