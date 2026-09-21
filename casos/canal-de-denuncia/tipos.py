"""The typed decision for the whistleblowing case: six signals, and urgency composed from them.

The questions are in Portuguese because the reports being judged are. TypeSafe's model card
says accuracy is best in English, which makes the question language a variable of the
experiment rather than a detail - see ``docs/metodologia.md``.

Nothing here asks "how urgent is this?" in a single field. A question that weighs several
things at once does not fail loudly: it returns a plausible number with low confidence.
Each signal is asked on its own, and ``compor_urgencia`` turns them into a level in Python,
where the rule is readable, arguable with legal, and attributable when it is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from lab.esquemas import descrito

__all__ = [
    "Afetados",
    "Composicao",
    "Hierarquia",
    "Sinais",
    "Triagem",
    "Urgencia",
    "compor_urgencia",
]


class Urgencia(IntEnum):
    """How fast the report has to be looked at. An ordinal rubric, scored as one."""

    ROTINA = 0
    """Rotina: apurar no fluxo normal de trabalho, sem prazo especial."""

    RELEVANTE = 1
    """Relevante: apurar dentro da semana."""

    GRAVE = 2
    """Grave: apurar em 24 horas. Ha continuidade do fato, poder hierarquico envolvido
    ou mais de uma pessoa afetada."""

    CRITICO = 3
    """Critico: risco fisico, retaliacao em curso ou ilicito acontecendo agora.
    Exige resposta imediata."""


class Hierarquia(StrEnum):
    """Where the accused sits relative to the person reporting."""

    PAR = "par"
    """Colega de mesmo nivel, sem poder formal sobre quem relata."""

    GESTOR_DIRETO = "gestor_direto"
    """Chefe imediato de quem relata, ou de quem foi afetado."""

    ALTA_LIDERANCA = "alta_lideranca"
    """Diretoria, socio, conselho ou executivo de primeiro escalao."""

    EXTERNO = "externo"
    """Fornecedor, cliente, terceirizado ou qualquer pessoa de fora do quadro."""

    INDETERMINADO = "indeterminado"
    """O relato nao permite dizer quem e o acusado nem que posicao ocupa."""


class Afetados(StrEnum):
    """How far the reported facts reach."""

    UMA_PESSOA = "uma_pessoa"
    """Apenas uma pessoa e atingida pelo que se relata."""

    UM_TIME = "um_time"
    """Um time, setor ou grupo determinado de pessoas e atingido."""

    EMPRESA_TODA = "empresa_toda"
    """O alcance e a empresa inteira, ou pessoas de fora dela."""

    INDETERMINADO = "indeterminado"
    """O relato nao permite dizer quantas pessoas sao atingidas."""


# The enums as fields see them: same type, schema carrying one description per option.
# Jev reads those descriptions as the meaning of each option and, for the rubric, refuses
# the request outright if a level has none.
NivelDeUrgencia = Annotated[Urgencia, descrito(Urgencia)]
PosicaoDoAcusado = Annotated[Hierarquia, descrito(Hierarquia)]
AlcanceDoRelato = Annotated[Afetados, descrito(Afetados)]


class Sinais(BaseModel):
    """The six signals, one question each.

    Each description is the question the model is asked. They are deliberately about
    observable facts in the text, never about how serious the reader should find it.
    """

    risco_fisico_iminente: bool = Field(
        description=(
            "O relato descreve risco a integridade fisica de alguem, seja agressao, "
            "ameaca de agressao, condicao insegura de trabalho ou risco a saude?"
        )
    )
    em_andamento: bool = Field(
        description=(
            "O fato relatado continua acontecendo agora, ou se repete, em vez de ser um "
            "episodio isolado e ja encerrado?"
        )
    )
    retaliacao: bool = Field(
        description=(
            "Ha ameaca, punicao, perseguicao ou prejuizo dirigido a quem relata ou a quem "
            "testemunhou, por causa do relato ou da recusa em participar?"
        )
    )
    hierarquia_do_acusado: PosicaoDoAcusado = Field(
        description="Que posicao a pessoa acusada ocupa em relacao a quem relata?"
    )
    afetados: AlcanceDoRelato = Field(
        description="Qual o alcance do que se relata, em numero de pessoas atingidas?"
    )
    tem_evidencia: bool = Field(
        description=(
            "O relato cita alguma evidencia verificavel, como anexo, documento, mensagem, "
            "registro de sistema ou testemunha identificavel?"
        )
    )


class Triagem(Sinais):
    """The six signals plus the composite level asked straight out, for comparison.

    ``urgencia_direta`` is the field the whole design argues against. It is asked anyway,
    in the same request, so the article can compare it against the level composed from the
    signals instead of asserting the difference. One extra question costs one extra
    question; being wrong about which approach works costs the argument.
    """

    urgencia_direta: NivelDeUrgencia = Field(
        description="Considerando tudo, qual o grau de urgencia da apuracao deste relato?"
    )


@dataclass(frozen=True)
class Composicao:
    """An urgency level and the rule that produced it."""

    urgencia: Urgencia | None
    """The composed level, or ``None`` when a signal is indeterminate and the case abstains."""

    regra: str
    """The code of the rule that fired, for auditing a label or a mistake."""

    motivo: str
    """What the rule says, in the words it would be argued in."""


# The ladder, in order. The first rule that matches decides, so a rule never has to
# exclude the ones above it. Evidence is asked and measured but deliberately absent:
# it changes how an investigation proceeds, not how fast it has to start. Saying so here
# is what keeps it from quietly becoming a tiebreaker later.
_SUPERIOR = (Hierarquia.GESTOR_DIRETO, Hierarquia.ALTA_LIDERANCA)
_VARIOS = (Afetados.UM_TIME, Afetados.EMPRESA_TODA)


def compor_urgencia(sinais: Sinais) -> Composicao:
    """Compose the urgency level from the signals, deterministically.

    Args:
        sinais: The six signals, however they were obtained - from a model, from the
            grammar that generated a synthetic case, or from a human label.

    Returns:
        The level and the rule that fired. An indeterminate signal that the ladder would
        have read returns ``None``: the case abstains instead of guessing, and it is scored
        on abstention rather than on accuracy.
    """
    superior = sinais.hierarquia_do_acusado in _SUPERIOR
    varios = sinais.afetados in _VARIOS

    if sinais.risco_fisico_iminente:
        return Composicao(Urgencia.CRITICO, "R1", "Ha risco fisico iminente.")
    if sinais.retaliacao and sinais.em_andamento:
        return Composicao(Urgencia.CRITICO, "R2", "Ha retaliacao em curso.")

    indeterminado = (
        sinais.hierarquia_do_acusado is Hierarquia.INDETERMINADO
        or sinais.afetados is Afetados.INDETERMINADO
    )
    if indeterminado:
        return Composicao(
            None,
            "R0",
            "Um sinal necessario para decidir ficou indeterminado; o caso vai para revisao humana.",
        )

    if sinais.retaliacao:
        return Composicao(Urgencia.GRAVE, "R3", "Houve retaliacao, ainda que ja encerrada.")
    if sinais.em_andamento and (superior or varios):
        return Composicao(
            Urgencia.GRAVE,
            "R4",
            "O fato continua acontecendo e envolve poder hierarquico ou varias pessoas.",
        )
    if superior and varios:
        return Composicao(
            Urgencia.GRAVE,
            "R5",
            "Poder hierarquico e varias pessoas afetadas, mesmo sem continuidade.",
        )
    if sinais.em_andamento or superior or varios:
        return Composicao(
            Urgencia.RELEVANTE,
            "R6",
            "Um agravante isolado: continuidade, hierarquia ou alcance.",
        )
    return Composicao(
        Urgencia.ROTINA, "R7", "Episodio isolado, entre pares, com uma pessoa afetada."
    )
