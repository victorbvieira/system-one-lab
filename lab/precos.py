"""Fixed price tables, read from dated files in ``precos/``.

Prices move. A published number that cannot say which price file it used rots in three
months, so nothing here looks a price up at runtime: a table is a file on disk, named after
the day it was collected, and every result records which one it used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

__all__ = [
    "Maquina",
    "Preco",
    "TabelaDePrecos",
    "arquivos_de_precos",
    "carregar_precos",
]


def raiz_dos_precos() -> Path:
    """The ``precos/`` directory of this working copy."""
    return Path(__file__).resolve().parent.parent / "precos"


@dataclass(frozen=True)
class Preco:
    """What one model costs per million tokens, in dollars."""

    entrada: float
    saida: float
    janela: int | None = None

    def custo(self, tokens_de_entrada: int, tokens_de_saida: int) -> float:
        """Cost in dollars for one request's token counts."""
        return (tokens_de_entrada * self.entrada + tokens_de_saida * self.saida) / 1_000_000


@dataclass(frozen=True)
class Maquina:
    """What an hour of a machine costs, for a model that runs on your own hardware.

    A local model has no price per token. It has a price per hour that runs whether or not
    a report arrives, which makes its cost per decision a function of utilisation - an axis
    that does not exist for an API.
    """

    usd_por_hora: float
    descricao: str = ""

    def custo(self, segundos: float) -> float:
        """Cost in dollars for a stretch of wall clock."""
        return self.usd_por_hora * segundos / 3600


@dataclass(frozen=True)
class TabelaDePrecos:
    """Every price collected on one day from one source, plus the exchange rate of that day."""

    arquivos: tuple[str, ...]
    """The file names this table was built from. Recorded in every result."""

    coletado_em: tuple[str, ...]
    precos: dict[str, Preco]
    cambio_usd_brl: float
    fonte_do_cambio: str
    maquinas: dict[str, Maquina] = field(default_factory=dict)

    def de(self, modelo: str) -> Preco:
        """The price of a model, by the id the price file uses.

        Raises:
            KeyError: If the model is not priced. A benchmark that guesses a price is
                worse than one that stops.
        """
        if modelo not in self.precos:
            conhecidos = ", ".join(sorted(self.precos)) or "nenhum"
            raise KeyError(
                f"Sem preco fixado para {modelo!r} nos arquivos {', '.join(self.arquivos)}. "
                f"Precificados: {conhecidos}."
            )
        return self.precos[modelo]

    def maquina(self, nome: str) -> Maquina:
        """The hourly price of a machine, by the name the price file uses.

        Raises:
            KeyError: If the machine is not priced. Guessing what someone's hardware costs
                is worse than stopping.
        """
        if nome not in self.maquinas:
            conhecidas = ", ".join(sorted(self.maquinas)) or "nenhuma"
            raise KeyError(
                f"Sem preco fixado para a maquina {nome!r}. Precificadas: {conhecidas}. "
                f"Edite precos/maquinas-*.json com o custo real da sua."
            )
        return self.maquinas[nome]

    def em_reais(self, dolares: float) -> float:
        """Convert using the rate recorded alongside the prices, never a live one."""
        return dolares * self.cambio_usd_brl


def arquivos_de_precos() -> list[Path]:
    """Every price file on disk, newest name last."""
    return sorted(raiz_dos_precos().glob("*.json"))


def carregar_precos(*caminhos: Path | str) -> TabelaDePrecos:
    """Load one or more price files into a single table.

    Args:
        caminhos: Price files. With none given, every file in ``precos/`` whose date is the
            most recent one present is used, which is how a run gets today's tables without
            naming them.

    Returns:
        The merged table.

    Raises:
        ValueError: If two files price the same model differently, or if the files disagree
            on the exchange rate. Silently picking one would make the published number
            depend on file order.
    """
    escolhidos = [Path(c) for c in caminhos] if caminhos else _mais_recentes()
    if not escolhidos:
        raise FileNotFoundError(f"Nenhum arquivo de preco em {raiz_dos_precos()}.")

    precos: dict[str, Preco] = {}
    maquinas: dict[str, Maquina] = {}
    coletas: list[str] = []
    cambios: dict[float, str] = {}
    for caminho in escolhidos:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        coletas.append(str(dados["coletado_em"]))
        for nome, valores in (dados.get("maquinas") or {}).items():
            maquinas[nome] = Maquina(
                usd_por_hora=float(valores["usd_por_hora"]),
                descricao=str(valores.get("descricao", "")),
            )
        for modelo, valores in (dados.get("modelos") or {}).items():
            novo = Preco(
                entrada=float(valores["entrada"]),
                saida=float(valores["saida"]),
                janela=valores.get("janela"),
            )
            if modelo in precos and precos[modelo] != novo:
                raise ValueError(
                    f"{modelo!r} tem dois precos diferentes entre os arquivos escolhidos. "
                    f"Escolha explicitamente qual tabela usar."
                )
            precos[modelo] = novo
        cambio = dados["cambio"]
        cambios[float(cambio["valor"])] = str(cambio["fonte"])

    if len(cambios) > 1:
        raise ValueError(
            f"Os arquivos de preco trazem cambios diferentes ({sorted(cambios)}). "
            f"Use arquivos da mesma coleta."
        )
    valor, fonte = next(iter(cambios.items()))
    return TabelaDePrecos(
        arquivos=tuple(Path(c).name for c in escolhidos),
        coletado_em=tuple(sorted(set(coletas))),
        precos=precos,
        maquinas=maquinas,
        cambio_usd_brl=valor,
        fonte_do_cambio=fonte,
    )


def _mais_recentes() -> list[Path]:
    """The price files carrying the latest date found in ``precos/``."""
    arquivos = arquivos_de_precos()
    datas: dict[Path, date] = {}
    for caminho in arquivos:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        datas[caminho] = date.fromisoformat(str(dados["coletado_em"]))
    if not datas:
        return []
    ultima = max(datas.values())
    return [caminho for caminho, quando in datas.items() if quando == ultima]
