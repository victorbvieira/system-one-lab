"""The schema rewrite is what makes a rubric a rubric on the wire, so it is tested first."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated

import pytest
from pydantic import BaseModel

from lab.esquemas import descricoes_de_membros, descrito, esquema_descrito


class Nivel(IntEnum):
    """A two-level rubric."""

    BAIXO = 0
    """Nada a fazer com pressa."""

    ALTO = 1
    """Resolver hoje."""


class Cor(StrEnum):
    """Options with meanings."""

    VERDE = "verde"
    """Tudo certo."""

    VERMELHO = "vermelho"
    """Algo quebrou."""


class SemDoc(IntEnum):
    A = 0
    """So este tem."""

    B = 1


def test_le_docstring_de_cada_membro() -> None:
    assert descricoes_de_membros(Nivel) == {
        "BAIXO": "Nada a fazer com pressa.",
        "ALTO": "Resolver hoje.",
    }


def test_esquema_traz_const_e_descricao_na_ordem_declarada() -> None:
    assert esquema_descrito(Cor) == {
        "anyOf": [
            {"const": "verde", "description": "Tudo certo."},
            {"const": "vermelho", "description": "Algo quebrou."},
        ]
    }


def test_membro_sem_docstring_falha_cedo() -> None:
    with pytest.raises(ValueError, match="Missing: B"):
        descricoes_de_membros(SemDoc)


def test_campo_anotado_mantem_validacao_e_publica_descricoes() -> None:
    class Modelo(BaseModel):
        nivel: Annotated[Nivel, descrito(Nivel)]

    assert Modelo(nivel=Nivel.ALTO).nivel is Nivel.ALTO
    assert Modelo.model_validate({"nivel": 1}).nivel is Nivel.ALTO
    propriedade = Modelo.model_json_schema()["properties"]["nivel"]
    assert propriedade["anyOf"] == [
        {"const": 0, "description": "Nada a fazer com pressa."},
        {"const": 1, "description": "Resolver hoje."},
    ]
