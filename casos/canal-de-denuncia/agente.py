"""The agent under test: one typed decision over one report, on whichever model.

The same instructions and the same output type go to every model. The System One route
turns each field into a question; a language model gets the same fields as a tool schema.
Anything that differs between the two beyond that would be measuring the harness.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from lab.casos import carregar_caso
from lab.modelos import Ajustes, construir

_CASO = carregar_caso("canal-de-denuncia")
tipos = _CASO.modulo("tipos")

INSTRUCOES_PADRAO = (
    "Voce faz a triagem de relatos de um canal de denuncia interno de uma empresa "
    "brasileira. O texto e o relato, escrito por quem denuncia, e pode estar em qualquer "
    "registro: formal, coloquial, telegrafico, com erro de digitacao. Responda cada "
    "pergunta apenas sobre o que o relato afirma ou descreve, nunca sobre o que voce "
    "supoe que possa ter acontecido. Uma negacao explicita e uma resposta, nao uma "
    "ausencia. Se o relato nao permitir concluir, prefira a opcao indeterminada."
)

NOME_DO_CASO = "canal-de-denuncia"
TIPO_DE_SAIDA = tipos.Triagem


def construir_agente(apelido: str, ajustes: Ajustes | None = None) -> Agent[None, Any]:
    """Build the triage agent on one catalogued model.

    Args:
        apelido: Model nickname, as in ``lab.modelos.CATALOGO``.
        ajustes: Settings. ``ajustes.instrucoes`` overrides the default framing, which is
            what the panel edits when comparing prompts.

    Returns:
        An agent whose output is the case's ``Triagem``.
    """
    ajustes = ajustes or Ajustes()
    return Agent(
        construir(apelido, ajustes),
        output_type=TIPO_DE_SAIDA,
        instructions=ajustes.instrucoes or INSTRUCOES_PADRAO,
        name=f"triagem-{apelido}",
        retries=2,
    )
