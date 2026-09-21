"""Export the results as one self-contained HTML page.

No CDN, no build step, no server: a single file with the data embedded, which can be
committed, opened from disk and published through GitHub Pages. That matters here because
``resultados/`` is versioned so anyone can read the numbers without holding a key - and a
dashboard that needs a running process is not readable by anyone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab.metricas import SINAIS
from lab.modelos import CATALOGO
from lab.relatorio import linha_de_procedencia
from lab.resultados import (
    Execucao,
    carregar_execucao,
    execucoes_existentes,
    raiz_dos_resultados,
)

__all__ = ["exportar", "montar_dados", "ultimas_execucoes"]

MODELO_DE_PAGINA = Path(__file__).resolve().parent / "modelo_de_pagina" / "dashboard.html"

# Field names are long and the heatmap has six columns. Truncating them in the page ran
# two headings together; naming them here keeps the axis readable and the key intact.
ROTULOS_DE_SINAL = {
    "risco_fisico_iminente": "risco fisico",
    "em_andamento": "continuidade",
    "retaliacao": "retaliacao",
    "hierarquia_do_acusado": "hierarquia",
    "afetados": "afetados",
    "tem_evidencia": "evidencia",
}


def ultimas_execucoes(caso: str) -> list[Execucao]:
    """The most recent run per model, which is what a comparison shows by default."""
    por_modelo: dict[str, Execucao] = {}
    for caminho in sorted(execucoes_existentes(caso)):
        execucao = carregar_execucao(caminho)
        por_modelo[execucao.modelo] = execucao
    ordem = list(CATALOGO)
    return sorted(
        por_modelo.values(),
        key=lambda e: ordem.index(e.modelo) if e.modelo in ordem else len(ordem),
    )


def _significativo(valor: float, digitos: int = 2) -> str:
    """Format a cost keeping two significant digits.

    Costs here span four orders of magnitude, from cents per thousand triages to dollars
    per detection. A fixed number of decimals rounds the cheap one to a single digit and
    quietly loses the comparison the number exists to make.
    """
    if valor == 0:
        return "0"
    from math import floor, log10

    casas = max(0, digitos - 1 - floor(log10(abs(valor))))
    return f"{valor:.{casas}f}".rstrip("0").rstrip(".")


def _kpis(execucoes: list[Execucao]) -> list[dict[str, str]]:
    """The four numbers the page leads with, each naming the model that earned it."""
    kpis: list[dict[str, str]] = []

    def melhor(chave: str, maior_e_melhor: bool) -> tuple[Execucao, float] | None:
        candidatos = [
            (e, e.metricas[chave])
            for e in execucoes
            if isinstance(e.metricas.get(chave), int | float)
        ]
        if not candidatos:
            return None
        return (max if maior_e_melhor else min)(candidatos, key=lambda item: item[1])

    if (vencedor := melhor("recall_nivel_3", True)) is not None:
        execucao, valor = vencedor
        kpis.append(
            {
                "rotulo": "Melhor recall de nivel 3",
                "valor": f"{valor * 100:.1f}%",
                "quem": f"{execucao.modelo} ({execucao.modelo_id})",
            }
        )
    if (vencedor := melhor("custo_usd_por_nivel_3_detectado", False)) is not None:
        execucao, valor = vencedor
        kpis.append(
            {
                "rotulo": "Menor custo por nivel 3 detectado",
                "valor": f"US$ {_significativo(valor)}",
                "quem": execucao.modelo,
            }
        )
    if (vencedor := melhor("custo_usd_por_mil", False)) is not None:
        execucao, valor = vencedor
        kpis.append(
            {
                "rotulo": "Menor custo por mil triagens",
                "valor": f"US$ {_significativo(valor)}",
                "quem": execucao.modelo,
            }
        )
    com_calibracao = [e for e in execucoes if e.metricas.get("erro_de_calibracao") is not None]
    kpis.append(
        {
            "rotulo": "Reportam confianca",
            "valor": f"{len(com_calibracao)}/{len(execucoes)}",
            "quem": (
                ", ".join(e.modelo for e in com_calibracao)
                if com_calibracao
                else "nenhum modelo desta comparacao"
            ),
        }
    )
    return kpis


def _razao_de_custo(execucoes: list[Execucao]) -> str:
    """The sentence the cost chart needs: how many times cheaper, and than what."""
    validos = [
        (e.modelo, e.metricas["custo_usd_por_nivel_3_detectado"])
        for e in execucoes
        if isinstance(e.metricas.get("custo_usd_por_nivel_3_detectado"), int | float)
        and e.metricas["custo_usd_por_nivel_3_detectado"] > 0
    ]
    if len(validos) < 2:
        return "Escala linear. Com uma execucao so nao ha razao a comparar."
    barato = min(validos, key=lambda item: item[1])
    caro = max(validos, key=lambda item: item[1])
    return (
        f"Escala linear. {barato[0]} sai {caro[1] / barato[1]:.0f} vezes mais barato que "
        f"{caro[0]} por denuncia critica corretamente detectada."
    )


def montar_dados(caso: str, execucoes: list[Execucao] | None = None) -> dict[str, Any]:
    """Everything the page needs, as one JSON-serializable dictionary."""
    escolhidas = execucoes if execucoes is not None else ultimas_execucoes(caso)
    system_one = next(
        (
            e.modelo
            for e in escolhidas
            if CATALOGO.get(e.modelo, None) and CATALOGO[e.modelo].system_one
        ),
        None,
    )
    sem_confianca = [e.modelo for e in escolhidas if e.metricas.get("erro_de_calibracao") is None]

    return {
        "caso": caso,
        "subtitulo": (
            f"{caso} · {len(escolhidas)} modelos · "
            + (
                f"{escolhidas[0].dataset['selecionados']} casos de "
                f"{escolhidas[0].dataset['arquivo']} · "
                f"{escolhidas[0].repeticoes} repeticoes"
                if escolhidas
                else "nenhuma execucao gravada"
            )
        ),
        "destaque": system_one,
        "sinais": [{"chave": nome, "curto": ROTULOS_DE_SINAL[nome]} for nome in SINAIS],
        "kpis": _kpis(escolhidas),
        "legenda_recall": (
            "O limiar de risco e mais baixo para os campos onde um falso negativo custa "
            "caro; a dica de cada barra mostra o recall com ele aplicado."
        ),
        "legenda_custo": _razao_de_custo(escolhidas),
        "legenda_calibracao": (
            "Sem confianca reportada: " + ", ".join(sem_confianca) + ". "
            "Um modelo que nao reporta confianca nao pode ser calibrado, nem roteado por ela."
            if sem_confianca
            else "Todos os modelos desta comparacao reportam confianca."
        ),
        "procedencia": [
            f"<b>{e.modelo}</b> — {linha_de_procedencia(e)} — execucao <code>{e.id}</code>"
            for e in escolhidas
        ],
        "execucoes": [
            {
                "modelo": e.modelo,
                "modelo_id": e.modelo_id,
                "rota": e.rota,
                "id": e.id,
                "metricas": e.metricas,
            }
            for e in escolhidas
        ],
    }


def exportar(caso: str, destino: Path | None = None) -> Path:
    """Write the dashboard.

    Args:
        caso: Which case to show.
        destino: Where to write. Defaults to ``resultados/<caso>/dashboard.html``, which is
            versioned along with the numbers it shows.

    Returns:
        The path written.
    """
    dados = montar_dados(caso)
    pagina = MODELO_DE_PAGINA.read_text(encoding="utf-8").replace(
        "/*__DADOS__*/{}", json.dumps(dados, ensure_ascii=False)
    )
    caminho = destino or (raiz_dos_resultados() / caso / "dashboard.html")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(pagina, encoding="utf-8")
    return caminho
