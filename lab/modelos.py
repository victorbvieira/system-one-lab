"""The model catalogue: who is being compared, by which route, and at which fixed version.

Jev is reached through TypeSafe's own API rather than OpenRouter. Two reasons, and the
second one is the whole experiment: OpenRouter does not serve it, and a System One model
reached through a chat completion would return an answer without the confidence and the
probability distribution behind it - which is metric 8, and half of what there is to say.

Every id here is pinned. Aliases move when a release ships, and a threshold tuned against
one version stops meaning anything on the next.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - import cost only paid when a run needs a model
    from pydantic_ai.models import Model

__all__ = ["CATALOGO", "Ajustes", "Modelo", "construir", "modelo", "modelos_por_rota"]

Rota = Literal["typesafe", "openrouter"]


@dataclass(frozen=True)
class Modelo:
    """One competitor in the comparison."""

    apelido: str
    """Short name used on the command line, in results and in the dashboard."""

    rota: Rota
    """Which API the request goes to."""

    id_na_rota: str
    """The exact, pinned id the provider expects."""

    id_de_preco: str
    """The key this model is priced under in ``precos/``."""

    papel: str
    """What it is here to represent, in the words the article uses."""

    observacao: str
    variavel_de_chave: str
    system_one: bool = False
    """True for a model that answers typed questions with calibrated probabilities."""

    @property
    def tem_chave(self) -> bool:
        """Whether the key this model needs is set in the environment."""
        return bool(os.getenv(self.variavel_de_chave))


CATALOGO: dict[str, Modelo] = {
    "jev": Modelo(
        apelido="jev",
        rota="typesafe",
        id_na_rota="jev-1.13.0",
        id_de_preco="jev-1.13.0",
        papel="System One",
        observacao=(
            "US$ 0,042 por milhao de tokens de entrada, saida gratuita, 32k de estado. "
            "Nao escreve texto: responde perguntas tipadas com confianca e distribuicao."
        ),
        variavel_de_chave="TYPESAFE_API_KEY",
        system_one=True,
    ),
    "sol": Modelo(
        apelido="sol",
        rota="openrouter",
        id_na_rota="openai/gpt-5.6-sol",
        id_de_preco="openai/gpt-5.6-sol",
        papel="Fronteira EUA",
        observacao="Teto de qualidade da comparacao.",
        variavel_de_chave="OPENROUTER_API_KEY",
    ),
    "opus": Modelo(
        apelido="opus",
        rota="openrouter",
        id_na_rota="anthropic/claude-opus-5",
        id_de_preco="anthropic/claude-opus-5",
        papel="Fronteira EUA",
        observacao="Segundo teto: mostra se o resultado e do modelo ou da familia.",
        variavel_de_chave="OPENROUTER_API_KEY",
    ),
    "luna": Modelo(
        apelido="luna",
        rota="openrouter",
        id_na_rota="openai/gpt-5.6-luna",
        id_de_preco="openai/gpt-5.6-luna",
        papel="Barato EUA",
        observacao="O concorrente honesto do Jev em custo.",
        variavel_de_chave="OPENROUTER_API_KEY",
    ),
    "deepseek": Modelo(
        apelido="deepseek",
        rota="openrouter",
        id_na_rota="deepseek/deepseek-v4.1-flash",
        id_de_preco="deepseek/deepseek-v4.1-flash",
        papel="Fronteira China",
        observacao="Referencia de custo-beneficio.",
        variavel_de_chave="OPENROUTER_API_KEY",
    ),
    "qwen": Modelo(
        apelido="qwen",
        rota="openrouter",
        id_na_rota="qwen/qwen3.8-27b",
        id_de_preco="qwen/qwen3.8-27b",
        papel="Fronteira China",
        observacao="Segunda referencia, modelo aberto.",
        variavel_de_chave="OPENROUTER_API_KEY",
    ),
}


@dataclass
class Ajustes:
    """How a model is asked, and everything about that which a result has to record.

    Defaults are the ones a run uses when nobody changes anything, which makes them part of
    the published method rather than a detail of the code.
    """

    limiar_booleano: float = 0.5
    """Where a ``bool`` answer flips to True, for the System One route.

    Jev answers a yes/no with the probability of yes; this is the bar that rounds it.
    """

    limiar_de_risco: float = 0.3
    """The lower bar applied, in post-processing, to the fields where a miss is expensive.

    A false negative on a level 3 costs far more than a false positive, so a True on a risk
    field only has to be plausible. It is applied after the response rather than in a second
    request: the raw probability of every boolean is recoverable from the reported
    confidence and the bar it was measured against - see ``lab.confianca``.
    """

    campos_de_risco: tuple[str, ...] = ("risco_fisico_iminente", "retaliacao", "em_andamento")
    temperatura: float = 0.0
    """Zero for the language models, so repetition measures the model's own variance."""

    tempo_limite: float = 60.0
    instrucoes: str | None = None
    """Extra framing sent with every request. Shared by both routes, so the comparison is fair."""

    extras: dict[str, Any] = field(default_factory=dict)

    def para_registro(self) -> dict[str, Any]:
        """The settings as they are recorded in a result file."""
        return {
            "limiar_booleano": self.limiar_booleano,
            "limiar_de_risco": self.limiar_de_risco,
            "campos_de_risco": list(self.campos_de_risco),
            "temperatura": self.temperatura,
            "tempo_limite": self.tempo_limite,
            "instrucoes": self.instrucoes,
            **self.extras,
        }


def modelo(apelido: str) -> Modelo:
    """Look a model up by nickname.

    Raises:
        KeyError: With the catalogue listed, since a typo here otherwise surfaces as a
            provider error halfway through a run.
    """
    if apelido not in CATALOGO:
        raise KeyError(f"Modelo {apelido!r} desconhecido. Catalogo: {', '.join(CATALOGO)}.")
    return CATALOGO[apelido]


def modelos_por_rota(rota: Rota) -> list[Modelo]:
    """Every catalogued model reached through one API."""
    return [m for m in CATALOGO.values() if m.rota == rota]


def construir(apelido: str, ajustes: Ajustes | None = None, atras: str | None = None) -> Model:
    """Build the Pydantic AI model for a nickname, reading its key from the environment.

    Args:
        apelido: A key of ``CATALOGO``.
        ajustes: How to ask. Defaults apply when omitted.
        atras: A second model to put behind the first, as a ``FallbackModel``. This is the
            arrangement metric 6 exists to judge: one that hands almost everything to the
            expensive model pays both bills and is slower than not using Jev at all, and
            the hand-off rate is what exposes that.

    Returns:
        A model ready to hand to an ``Agent``.

    Raises:
        RuntimeError: If the key this route needs is not set. Named explicitly, because
            the provider's own error does not say which of the two keys is missing.
    """
    if atras is not None:
        from pydantic_ai.models.fallback import FallbackModel

        return FallbackModel(construir(apelido, ajustes), construir(atras, ajustes))

    escolhido = modelo(apelido)
    ajustes = ajustes or Ajustes()
    chave = os.getenv(escolhido.variavel_de_chave)
    if not chave:
        raise RuntimeError(
            f"{escolhido.variavel_de_chave} nao esta definida, e {escolhido.apelido} precisa "
            f"dela. Copie .env.example para .env e preencha."
        )

    if escolhido.rota == "typesafe":
        from pydantic_ai.models.typesafe import TypeSafeModel, TypeSafeModelSettings
        from pydantic_ai.providers.typesafe import TypeSafeProvider

        return TypeSafeModel(
            escolhido.id_na_rota,
            provider=TypeSafeProvider(api_key=chave),
            settings=TypeSafeModelSettings(
                typesafe_boolean_threshold=ajustes.limiar_booleano,
                timeout=ajustes.tempo_limite,
            ),
        )

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider
    from pydantic_ai.settings import ModelSettings

    return OpenAIChatModel(
        escolhido.id_na_rota,
        provider=OpenRouterProvider(api_key=chave),
        settings=ModelSettings(temperature=ajustes.temperatura, timeout=ajustes.tempo_limite),
    )
