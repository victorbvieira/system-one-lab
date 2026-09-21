"""Turn a finished run into something a person can read and a file can hold.

Two views of the same run, because they answer different questions. ``passos`` is the
distilled one the panel shows - who said what, which tools were called, what each field's
confidence was. ``mensagens`` is the raw message history, kept whole, because a distilled
trace always turns out to be missing exactly the field being argued about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

__all__ = ["Parte", "Passo", "Traco", "extrair_traco"]


@dataclass
class Parte:
    """One piece of one step: a prompt, a tool call, a result, a thought."""

    tipo: str
    """``instrucoes``, ``prompt``, ``texto``, ``pensamento``, ``chamada_de_tool``,
    ``retorno_de_tool`` or ``nova_tentativa``."""

    conteudo: str
    detalhes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Passo:
    """One request to a model, or one response from it."""

    indice: int
    origem: str
    """``requisicao`` or ``resposta``."""

    partes: list[Parte]
    modelo: str | None = None
    tokens_de_entrada: int | None = None
    tokens_de_saida: int | None = None
    motivo_do_fim: str | None = None
    detalhes_do_provedor: dict[str, Any] = field(default_factory=dict)
    """For the System One route: confidence, probabilities and scores, per field."""


@dataclass
class Traco:
    """Everything one run of the agent did."""

    passos: list[Passo]
    mensagens: list[dict[str, Any]]
    """The raw history, as JSON. The distilled steps are a reading of this, not a
    replacement for it."""

    chamadas_de_tool: list[str]
    requisicoes: int
    """How many requests the step really cost. The System One route reports 2 when it had
    to pick a route and then fill it, which usage alone cannot say."""

    confianca: dict[str, float] = field(default_factory=dict)
    probabilidades: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)


def _partes_da_requisicao(mensagem: ModelRequest) -> list[Parte]:
    partes: list[Parte] = []
    if instrucoes := getattr(mensagem, "instructions", None):
        partes.append(Parte("instrucoes", str(instrucoes)))
    for parte in mensagem.parts:
        if isinstance(parte, SystemPromptPart):
            partes.append(Parte("instrucoes", parte.content))
        elif isinstance(parte, UserPromptPart):
            partes.append(Parte("prompt", _texto(parte.content)))
        elif isinstance(parte, ToolReturnPart):
            partes.append(
                Parte(
                    "retorno_de_tool",
                    _texto(parte.content),
                    {"tool": parte.tool_name, "id": parte.tool_call_id},
                )
            )
        elif isinstance(parte, RetryPromptPart):
            partes.append(Parte("nova_tentativa", _texto(parte.content)))
    return partes


def _partes_da_resposta(mensagem: ModelResponse) -> tuple[list[Parte], list[str]]:
    partes: list[Parte] = []
    tools: list[str] = []
    for parte in mensagem.parts:
        if isinstance(parte, TextPart):
            partes.append(Parte("texto", parte.content))
        elif isinstance(parte, ThinkingPart):
            partes.append(Parte("pensamento", parte.content))
        elif isinstance(parte, ToolCallPart):
            tools.append(parte.tool_name)
            partes.append(
                Parte(
                    "chamada_de_tool",
                    parte.tool_name,
                    {"argumentos": parte.args, "id": parte.tool_call_id},
                )
            )
    return partes, tools


def _texto(conteudo: Any) -> str:
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n".join(_texto(item) for item in conteudo)
    return str(conteudo)


def extrair_traco(mensagens: list[ModelMessage]) -> Traco:
    """Read a run's message history into steps, and lift what the provider reported.

    Args:
        mensagens: ``result.all_messages()``.

    Returns:
        The trace, with the System One details lifted to the top for the metrics that read
        them.
    """
    passos: list[Passo] = []
    chamadas: list[str] = []
    requisicoes = 0
    confianca: dict[str, float] = {}
    probabilidades: dict[str, Any] = {}
    scores: dict[str, float] = {}

    for indice, mensagem in enumerate(mensagens):
        if isinstance(mensagem, ModelRequest):
            passos.append(Passo(indice, "requisicao", _partes_da_requisicao(mensagem)))
            continue

        partes, tools = _partes_da_resposta(mensagem)
        chamadas.extend(tools)
        detalhes = dict(mensagem.provider_details or {})
        # `requests` is only present when one step cost two requests, which is exactly
        # when it matters; otherwise the step cost one.
        requisicoes += int(detalhes.get("requests", 1))
        confianca.update(detalhes.get("confidence") or {})
        probabilidades.update(detalhes.get("probabilities") or {})
        scores.update(detalhes.get("scores") or {})
        passos.append(
            Passo(
                indice=indice,
                origem="resposta",
                partes=partes,
                modelo=mensagem.model_name,
                tokens_de_entrada=getattr(mensagem.usage, "input_tokens", None),
                tokens_de_saida=getattr(mensagem.usage, "output_tokens", None),
                motivo_do_fim=mensagem.finish_reason,
                detalhes_do_provedor=detalhes,
            )
        )

    return Traco(
        passos=passos,
        mensagens=ModelMessagesTypeAdapter.dump_python(mensagens, mode="json"),
        chamadas_de_tool=chamadas,
        requisicoes=requisicoes or 1,
        confianca=confianca,
        probabilidades=probabilidades,
        scores=scores,
    )
