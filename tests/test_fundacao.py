"""Smoke checks for the repository foundation.

Cheap invariants that must hold before any experiment exists: the packages
import, and no API key ever leaks into the example environment file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_pacotes_importam() -> None:
    import anonimizador
    import lab

    assert lab.__version__
    assert anonimizador.__version__


def test_env_example_nao_tem_valor_preenchido() -> None:
    """Rule 4: no API key in the repository, ever."""
    permitidos = {"LANGFUSE_HOST", "ANONIMIZADOR_ESCOPO_SALT"}
    for linha in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        chave, _, valor = linha.partition("=")
        assert valor == "" or chave in permitidos, f"{chave} tem valor em .env.example"


def test_projeto_exige_python_312() -> None:
    dados = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert dados["project"]["requires-python"] == ">=3.12"
