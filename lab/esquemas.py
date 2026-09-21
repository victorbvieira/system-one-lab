"""Turn member docstrings into the option descriptions a System One question needs.

Jev reads a field's schema, not the Python source: a rubric level or a choice option is
described by the ``description`` next to its value, and a rubric whose levels are
unexplained is refused before the request is sent. Python keeps no docstring for an enum
member, so this module recovers them from the source and rewrites the schema.

Writing the descriptions twice - once as a docstring, once in a dict - is how they drift.
The docstring is the single source, and ``Descrito`` is what puts it on the wire.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from enum import Enum
from typing import Any

from pydantic import WithJsonSchema

__all__ = ["descricoes_de_membros", "descrito", "esquema_descrito"]


def descricoes_de_membros(enum: type[Enum]) -> dict[str, str]:
    """Map each member name to the docstring written under its assignment.

    Args:
        enum: The enum class to read.

    Returns:
        One description per member, in declaration order.

    Raises:
        ValueError: If the source cannot be read, or a member has no docstring. Both are
            bugs in the case definition, and both are cheaper to hit here than as a 400.
    """
    try:
        fonte = textwrap.dedent(inspect.getsource(enum))
    except (OSError, TypeError) as erro:  # pragma: no cover - only outside a source file
        raise ValueError(
            f"Cannot read the source of {enum.__name__}, so its member docstrings are "
            f"unavailable. Declare the enum in a module on disk."
        ) from erro

    corpo = ast.parse(fonte).body[0]
    if not isinstance(corpo, ast.ClassDef):  # pragma: no cover - getsource gave us a class
        raise ValueError(f"{enum.__name__} did not parse as a class definition.")

    descricoes: dict[str, str] = {}
    pendente: str | None = None
    for no in corpo.body:
        alvos = no.targets if isinstance(no, ast.Assign) else []
        if len(alvos) == 1 and isinstance(alvos[0], ast.Name):
            pendente = alvos[0].id
            continue
        if (
            pendente is not None
            and isinstance(no, ast.Expr)
            and isinstance(no.value, ast.Constant)
            and isinstance(no.value.value, str)
        ):
            descricoes[pendente] = inspect.cleandoc(no.value.value)
        pendente = None

    faltando = [membro.name for membro in enum if membro.name not in descricoes]
    if faltando:
        raise ValueError(
            f"Every member of {enum.__name__} needs a docstring: it is the description the "
            f"model reads. Missing: {', '.join(faltando)}."
        )
    return descricoes


def esquema_descrito(enum: type[Enum]) -> dict[str, Any]:
    """The JSON schema for an enum, with one described ``const`` per member.

    A plain enum serializes to a bare ``enum`` list, which carries no descriptions. The
    ``anyOf`` of ``const`` is the shape the TypeSafe model reads option meanings from, and
    it is ordinary JSON Schema, so the language-model baselines read it too.
    """
    descricoes = descricoes_de_membros(enum)
    return {
        "anyOf": [
            {"const": membro.value, "description": descricoes[membro.name]} for membro in enum
        ]
    }


def descrito(enum: type[Enum]) -> WithJsonSchema:
    """Schema metadata that gives an enum field one description per option.

    Used as the annotation's metadata, which keeps the declared type honest for a type
    checker while rewriting what the model sees::

        Nivel = Annotated[Urgencia, descrito(Urgencia)]

    Validation is unchanged: the field is still the enum.
    """
    return WithJsonSchema(esquema_descrito(enum))
