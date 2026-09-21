"""The shape of a result file, and where it is written.

``resultados/`` is versioned on purpose: anyone can read the numbers without holding a key.
That only works if a result file carries everything needed to judge it - the pinned model
version, the price file, the dataset and its seed, the repetitions and the settings. A
number without those four is not publishable, so they are fields here, not conventions.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "Execucao",
    "ResultadoDeCaso",
    "caminho_da_execucao",
    "carregar_execucao",
    "escrever_execucao",
    "execucoes_existentes",
    "raiz_dos_resultados",
]


def raiz_dos_resultados() -> Path:
    """The ``resultados/`` directory of this working copy."""
    return Path(__file__).resolve().parent.parent / "resultados"


@dataclass
class ResultadoDeCaso:
    """One model's answer for one case, on one repetition."""

    caso_id: str
    repeticao: int
    cenario: str
    registro: str

    esperado: dict[str, Any]
    obtido: dict[str, Any] = field(default_factory=dict)

    urgencia_esperada: int | None = None
    urgencia_composta: int | None = None
    urgencia_direta: int | None = None
    regra: str | None = None

    confianca: dict[str, float] = field(default_factory=dict)
    probabilidades: dict[str, Any] = field(default_factory=dict)
    probabilidades_booleanas: dict[str, float] = field(default_factory=dict)
    """Recovered from confidence for the System One route; empty for a language model."""

    releitura_de_risco: dict[str, Any] = field(default_factory=dict)
    """What the lower bar on the risk fields changed, and the level it composed to."""

    acertos: dict[str, bool] = field(default_factory=dict)
    latencia_ms: float = 0.0
    tokens_de_entrada: int = 0
    tokens_de_saida: int = 0
    requisicoes: int = 1
    chamadas_de_tool: list[str] = field(default_factory=list)
    custo_usd: float = 0.0
    custo_brl: float = 0.0
    handoff: bool = False
    """True when the System One route gave the step to the model behind it."""

    erro: str | None = None
    traco: dict[str, Any] | None = None
    """The full trace, kept for a sample of cases and for every failure. Keeping all of
    them would put hundreds of megabytes of message history in a versioned repository."""


@dataclass
class Execucao:
    """One model, one case, one dataset, one set of settings - and everything it produced."""

    id: str
    caso: str
    modelo: str
    modelo_id: str
    modelo_versao_reportada: str | None
    rota: str

    dataset: dict[str, Any]
    precos: dict[str, Any]
    ajustes: dict[str, Any]
    repeticoes: int
    subconjunto: dict[str, Any]

    inicio: str
    fim: str | None = None
    duracao_s: float = 0.0
    ambiente: dict[str, Any] = field(default_factory=dict)
    metricas: dict[str, Any] = field(default_factory=dict)
    casos: list[ResultadoDeCaso] = field(default_factory=list)
    erro: str | None = None

    def resumo(self) -> dict[str, Any]:
        """The one line that goes to ``history.jsonl``: enough to plot a series, no more."""
        return {
            "id": self.id,
            "caso": self.caso,
            "modelo": self.modelo,
            "modelo_id": self.modelo_id,
            "modelo_versao_reportada": self.modelo_versao_reportada,
            "inicio": self.inicio,
            "repeticoes": self.repeticoes,
            "casos": len({c.caso_id for c in self.casos}),
            "execucoes_de_caso": len(self.casos),
            "dataset": self.dataset.get("arquivo"),
            "dataset_semente": self.dataset.get("semente"),
            "precos": self.precos.get("arquivos"),
            "metricas": {
                chave: self.metricas.get(chave)
                for chave in (
                    "recall_nivel_3",
                    "precisao_nivel_3",
                    "acuracia_composta",
                    "acuracia_direta",
                    "custo_usd_por_mil",
                    "custo_usd_por_nivel_3_detectado",
                    "latencia_p50_ms",
                    "latencia_p95_ms",
                    "taxa_de_handoff",
                    "erro_de_calibracao",
                )
            },
        }


def ambiente_atual() -> dict[str, Any]:
    """Python, the library versions that decide behaviour, and the commit."""
    import platform
    from importlib.metadata import PackageNotFoundError, version

    pacotes: dict[str, str] = {}
    for nome in ("pydantic-ai-slim", "pydantic-evals", "typesafe-sdk", "pydantic", "faker"):
        try:
            pacotes[nome] = version(nome)
        except PackageNotFoundError:  # pragma: no cover - optional extras
            continue
    return {"python": platform.python_version(), "pacotes": pacotes, "commit": _commit()}


def _commit() -> str | None:
    try:
        saida = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - not a checkout
        return None
    return saida.stdout.strip() or None


def novo_id(modelo: str) -> str:
    """A run id that sorts by time and says what it was."""
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{modelo}"


def caminho_da_execucao(caso: str, modelo: str, id_da_execucao: str) -> Path:
    """``resultados/<caso>/<modelo>/<execucao>.json``."""
    return raiz_dos_resultados() / caso / modelo / f"{id_da_execucao}.json"


def escrever_execucao(execucao: Execucao) -> Path:
    """Write the result file and append its summary to the history.

    Returns:
        The path written.
    """
    destino = caminho_da_execucao(execucao.caso, execucao.modelo, execucao.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(asdict(execucao), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    historico = raiz_dos_resultados() / "history.jsonl"
    historico.parent.mkdir(parents=True, exist_ok=True)
    with historico.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(execucao.resumo(), ensure_ascii=False, default=str) + "\n")
    return destino


def carregar_execucao(caminho: Path) -> Execucao:
    """Read a result file back, including its per-case results."""
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    casos = [ResultadoDeCaso(**caso) for caso in dados.pop("casos", [])]
    return Execucao(**dados, casos=casos)


def execucoes_existentes(caso: str | None = None, modelo: str | None = None) -> list[Path]:
    """Every result file on disk, newest first."""
    raiz = raiz_dos_resultados()
    padrao = f"{caso or '*'}/{modelo or '*'}/*.json"
    return sorted(raiz.glob(padrao), key=lambda p: p.name, reverse=True)
