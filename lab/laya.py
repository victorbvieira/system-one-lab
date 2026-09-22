"""Run Laya, an open-weights System One model, as a Pydantic AI model.

Laya answers the same three typed questions as Jev - choice, score and noul - in one
forward pass of a 421M bidirectional encoder, and returns a probability distribution and a
calibrated confidence for each. Its ``predict(state, questions)`` takes the same question
shapes, so an agent written against one runs on the other.

The point of this module is that the *questions are built by Pydantic AI itself*. Writing a
second schema-to-question mapper here would let the two routes drift and silently ask the
two models different things - which would look like a difference between models and be a
difference between adapters. Instead the TypeSafe model's own mapping is reused and its
answers are fed back through its own reader, so what differs between the runs is the model
and nothing else.

That reuse is of private functions, and a Pydantic AI upgrade can move them. The import
below fails loudly with instructions when that happens, and ``tests/test_laya.py`` checks
the contract, so the failure is never silent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from anyio import to_thread
from pydantic_ai import usage
from pydantic_ai._utils import generate_tool_call_id
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters, check_allow_model_requests
from pydantic_ai.settings import ModelSettings
from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer

if TYPE_CHECKING:  # pragma: no cover
    from laya.agent import Agent as AgenteLaya

try:
    from pydantic_ai.models.typesafe import (
        _answers,  # pyright: ignore[reportPrivateUsage]
        _fields,  # pyright: ignore[reportPrivateUsage]
        _map_messages,  # pyright: ignore[reportPrivateUsage]
        _output_tools,  # pyright: ignore[reportPrivateUsage]
        _questions,  # pyright: ignore[reportPrivateUsage]
    )
except ImportError as erro:  # pragma: no cover - only on a Pydantic AI upgrade
    raise ImportError(
        "Esta rota reusa o mapeamento de esquema para pergunta do proprio Pydantic AI, "
        "para que o Jev e o Laya recebam perguntas identicas. A versao instalada mudou "
        "esses nomes. Conferir pydantic_ai.models.typesafe e atualizar lab/laya.py - nao "
        "escrever um segundo mapeamento, que e como as duas rotas passam a medir coisas "
        "diferentes sem ninguem notar."
    ) from erro

__all__ = ["CHECKPOINTS", "ModeloLaya", "carregar_agente"]

# The English root checkpoint collapses outside the Latin script and is not the one for
# Portuguese; the multilingual one covers 45 of 51 tested languages. The default here is
# the multilingual one because the corpus of this repository is in Portuguese.
CHECKPOINTS: dict[str, tuple[str, str | None]] = {
    "multilingual": ("convaiinnovations/laya", "multilingual"),
    "english": ("convaiinnovations/laya", None),
    "typed-decisions": ("convaiinnovations/laya", "typed-decisions"),
}


@lru_cache(maxsize=4)
def carregar_agente(checkpoint: str, dispositivo: str | None) -> AgenteLaya:
    """Load a Laya checkpoint once and keep it.

    A cold load takes seven to ten seconds and reads hundreds of megabytes from disk. Doing
    that per request would put the load time inside the latency being measured.

    Raises:
        ImportError: If the ``local`` extra is not installed.
        KeyError: If the checkpoint is not one of ``CHECKPOINTS``.
    """
    try:
        import laya
    except ImportError as erro:  # pragma: no cover - depends on the environment
        raise ImportError(
            "O pacote `laya` nao esta instalado. Rode `uv sync --extra local`, ou use a "
            "imagem Docker do projeto, que ja o traz."
        ) from erro

    if checkpoint not in CHECKPOINTS:
        raise KeyError(f"Checkpoint {checkpoint!r} desconhecido. Opcoes: {', '.join(CHECKPOINTS)}.")
    repositorio, subpasta = CHECKPOINTS[checkpoint]
    return laya.load(repositorio, device=dispositivo, subfolder=subpasta)


def _resposta_do_laya(bruta: dict[str, Any]) -> NoulAnswer | ChoiceAnswer | ScoreAnswer:
    """Turn one Laya answer into the object Pydantic AI's reader expects.

    The two payloads already carry the same fields; this is a change of type, not of
    meaning, and it is what lets the answers go back through Pydantic AI's own reader
    instead of a second one written here.
    """
    tipo = bruta["type"]
    if tipo == "noul":
        return NoulAnswer(noul=float(bruta["noul"]))
    if tipo == "choice":
        return ChoiceAnswer(
            choice=str(bruta["choice"]),
            confidence=float(bruta["confidence"]),
            probabilities={str(k): float(v) for k, v in bruta["probabilities"].items()},
        )
    if tipo == "score":
        return ScoreAnswer(
            score=float(bruta["score"]),
            confidence=float(bruta["confidence"]),
            legend={int(k): v for k, v in bruta["legend"].items()},
            probabilities={int(k): float(v) for k, v in bruta["probabilities"].items()},
        )
    raise UserError(f"Tipo de resposta desconhecido vindo do Laya: {tipo!r}.")


@dataclass(init=False)
class ModeloLaya(Model):
    """A local, open-weights System One model, asked exactly what the TypeSafe route is.

    Nothing leaves the machine. That is the property that matters for the pipeline this
    repository is a rehearsal for: a real report can be judged by this model without ever
    being sent to a third party, which is not true of any other model in the catalogue.
    """

    _checkpoint: str = field(repr=False)
    _dispositivo: str | None = field(repr=False)

    def __init__(
        self,
        checkpoint: str = "multilingual",
        *,
        dispositivo: str | None = None,
        settings: ModelSettings | None = None,
    ) -> None:
        """Set up the route.

        Args:
            checkpoint: One of ``CHECKPOINTS``. The multilingual one is the default because
                the corpus here is in Portuguese.
            dispositivo: ``cuda``, ``cpu``, or ``None`` to let Laya choose.
            settings: Model settings. Only ``typesafe_boolean_threshold`` is read, and it
                is read under that name on purpose: it is the same bar, doing the same job,
                and the run records it under one name for both routes.
        """
        self._checkpoint = checkpoint
        self._dispositivo = dispositivo
        super().__init__(settings=settings)

    @property
    def model_name(self) -> str:
        return f"laya-{self._checkpoint}"

    @property
    def system(self) -> str:
        return "local"

    @property
    def base_url(self) -> str | None:
        return None

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Answer one request, entirely on this machine."""
        check_allow_model_requests()
        model_settings, model_request_parameters = self.prepare_request(
            model_settings, model_request_parameters
        )
        if model_request_parameters.function_tools:
            raise UserError(
                "O Laya responde perguntas tipadas e nao chama tools. Para um arranjo com "
                "tools, ponha um modelo de linguagem atras dele com FallbackModel."
            )

        ferramentas_de_saida, _ = _output_tools(model_request_parameters)
        if len(ferramentas_de_saida) != 1:
            raise UserError(
                "Esta rota atende um `output_type` estruturado por vez. Uma uniao de tipos "
                "exigiria a pergunta de roteamento que o Jev faz, e ela ainda nao foi "
                "portada para ca."
            )

        ferramenta = ferramentas_de_saida[0]
        propriedades = _fields(ferramenta)
        partes_de_instrucao = self._get_instruction_parts(messages, model_request_parameters) or []
        instrucoes = "\n\n".join(parte.content for parte in partes_de_instrucao) or None
        perguntas = _questions(propriedades, ferramenta, instrucoes)
        estado = _map_messages(messages)

        limiar = float((model_settings or {}).get("typesafe_boolean_threshold", 0.5) or 0.5)  # type: ignore[arg-type]
        agente = carregar_agente(self._checkpoint, self._dispositivo)
        como_dicionario = {nome: p.model_dump(mode="json") for nome, p in perguntas.items()}

        inicio = time.perf_counter()
        # `predict` is synchronous and holds the GPU or the CPU for its duration; off the
        # event loop it would block every other case running concurrently.
        bruta = await to_thread.run_sync(lambda: agente.predict(estado, como_dicionario))
        decorrido = time.perf_counter() - inicio

        respostas = {nome: _resposta_do_laya(r) for nome, r in bruta["answers"].items()}
        argumentos, detalhes = _answers(respostas, propriedades, perguntas, limiar)
        detalhes["segundos_de_maquina"] = round(decorrido, 4)
        detalhes["checkpoint"] = self._checkpoint

        uso_bruto = bruta.get("usage") or {}
        return ModelResponse(
            parts=[ToolCallPart(ferramenta.name, argumentos, generate_tool_call_id())],
            usage=usage.RequestUsage(
                input_tokens=int(uso_bruto.get("input_tokens") or 0),
                output_tokens=int(uso_bruto.get("output_tokens") or 0),
            ),
            model_name=str(bruta.get("model") or self.model_name),
            provider_name="local",
            provider_details=detalhes,
            finish_reason="tool_call",
        )
