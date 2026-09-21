"""Load a case's modules from a directory whose name is not a Python identifier.

Case directories are named after the domain - ``canal-de-denuncia`` - because product
names never appear in paths here. A hyphen makes the directory unimportable by name, so
its modules are loaded by path.

The loaded module is registered in ``sys.modules`` before it is executed. Skipping that
registration breaks anything that looks its own module up by name while the class body
runs, which includes ``dataclasses`` resolving annotations: a ``@dataclass`` in a case
module fails with an obscure ``AttributeError`` instead of loading.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

__all__ = ["Caso", "carregar_caso", "casos_disponiveis", "raiz_dos_casos"]

_MODULOS = ("tipos", "agente", "gerar")


def raiz_dos_casos() -> Path:
    """The ``casos/`` directory of the working copy this package was imported from."""
    return Path(__file__).resolve().parent.parent / "casos"


def casos_disponiveis() -> list[str]:
    """Every case directory that defines at least a ``tipos.py``, sorted by name."""
    raiz = raiz_dos_casos()
    if not raiz.is_dir():
        return []
    return sorted(p.name for p in raiz.iterdir() if p.is_dir() and (p / "tipos.py").is_file())


@dataclass(frozen=True)
class Caso:
    """A case's directory and its loaded modules."""

    nome: str
    diretorio: Path
    tipos: ModuleType
    agente: ModuleType | None
    gerar: ModuleType | None

    def modulo(self, nome: str) -> ModuleType:
        """One of the case's optional modules, or a clear failure naming what is missing.

        ``caso.gerar`` is ``ModuleType | None`` because a case need not ship a generator.
        Callers that require one say so through this, instead of carrying the ``None``.
        """
        modulo = {"tipos": self.tipos, "agente": self.agente, "gerar": self.gerar}.get(nome)
        if modulo is None:
            raise AttributeError(f"O caso {self.nome!r} nao define {nome}.py.")
        return modulo

    @property
    def dataset(self) -> Path:
        """Where the generated dataset is written and read."""
        return self.diretorio / "dataset.yaml"

    @property
    def holdout(self) -> Path:
        """Where the hand-written holdout lives, if it exists yet."""
        return self.diretorio / "holdout.yaml"


def _carregar_modulo(nome_do_caso: str, caminho: Path) -> ModuleType:
    nome = f"casos.{nome_do_caso.replace('-', '_')}.{caminho.stem}"
    if (ja_carregado := sys.modules.get(nome)) is not None:
        return ja_carregado
    spec = importlib.util.spec_from_file_location(nome, caminho)
    if spec is None or spec.loader is None:  # pragma: no cover - unreadable file
        raise ImportError(f"Cannot load {caminho}")
    modulo = importlib.util.module_from_spec(spec)
    # Registered before execution, not after: the module body may need to find itself.
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    except BaseException:
        del sys.modules[nome]
        raise
    return modulo


def carregar_caso(nome: str) -> Caso:
    """Load a case by directory name.

    Args:
        nome: The directory name under ``casos/``, such as ``canal-de-denuncia``.

    Returns:
        The case, with ``tipos`` always loaded and the optional modules loaded when present.

    Raises:
        FileNotFoundError: If no such case directory exists, listing the ones that do.
    """
    diretorio = raiz_dos_casos() / nome
    if not (diretorio / "tipos.py").is_file():
        disponiveis = ", ".join(casos_disponiveis()) or "nenhum"
        raise FileNotFoundError(f"Caso {nome!r} nao encontrado. Disponiveis: {disponiveis}.")
    carregados = {
        modulo: (
            _carregar_modulo(nome, diretorio / f"{modulo}.py")
            if (diretorio / f"{modulo}.py").is_file()
            else None
        )
        for modulo in _MODULOS
    }
    tipos = carregados["tipos"]
    assert tipos is not None
    return Caso(
        nome=nome,
        diretorio=diretorio,
        tipos=tipos,
        agente=carregados["agente"],
        gerar=carregados["gerar"],
    )
