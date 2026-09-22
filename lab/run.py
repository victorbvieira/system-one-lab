"""The command line: run a model, compare runs, open the panel, export the dashboard.

Nothing here talks to a provider directly. It builds a ``Plano``, hands it to
``lab.execucao``, prints what came back and decides whether to keep it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from lab import relatorio
from lab.execucao import Plano, executar
from lab.modelos import CATALOGO, Ajustes
from lab.resultados import (
    Execucao,
    carregar_execucao,
    escrever_execucao,
    execucoes_existentes,
)

__all__ = ["main"]

console = Console()


def _analisador() -> argparse.ArgumentParser:
    principal = argparse.ArgumentParser(
        prog="lab",
        description="Laboratorio de comparacao entre um modelo System One e LLMs de fronteira.",
    )
    comandos = principal.add_subparsers(dest="comando", required=True)

    rodar = comandos.add_parser("rodar", help="roda um ou mais modelos sobre um caso")
    rodar.add_argument("--caso", default="canal-de-denuncia")
    rodar.add_argument(
        "--modelo",
        action="append",
        default=None,
        help=f"apelido do modelo, repetivel. Catalogo: {', '.join(CATALOGO)}",
    )
    rodar.add_argument(
        "--comparar",
        action="store_true",
        help="roda todos os modelos do catalogo que tiverem chave disponivel",
    )
    rodar.add_argument("--repeticoes", type=int, default=3)
    rodar.add_argument(
        "--limite",
        type=int,
        default=40,
        help="quantos casos sortear, balanceados por nivel. 0 roda o dataset inteiro",
    )
    rodar.add_argument("--fonte", choices=["dataset", "holdout"], default="dataset")
    rodar.add_argument("--cenario", action="append", default=None)
    rodar.add_argument("--registro", action="append", default=None)
    rodar.add_argument("--concorrencia", type=int, default=4)
    rodar.add_argument("--limiar-booleano", type=float, default=0.5)
    rodar.add_argument("--limiar-de-risco", type=float, default=0.3)
    rodar.add_argument("--tracos", choices=["amostra", "todos", "nenhum"], default="amostra")
    rodar.add_argument(
        "--dispositivo",
        default=None,
        choices=["cpu", "cuda"],
        help="para um modelo local: onde rodar. Sem isto, o proprio modelo escolhe",
    )
    rodar.add_argument(
        "--maquina",
        default="local-proprio",
        help=(
            "contra qual maquina de precos/maquinas-*.json cobrar uma execucao local. "
            "O padrao e hardware ja pago, com custo marginal zero"
        ),
    )
    rodar.add_argument(
        "--atras",
        default=None,
        help="modelo a colocar atras do primeiro, como FallbackModel, para medir hand-off",
    )
    rodar.add_argument(
        "--nao-salvar",
        action="store_true",
        help="imprime o resultado sem escrever em resultados/",
    )

    ver = comandos.add_parser("comparar", help="compara execucoes ja gravadas")
    ver.add_argument("--caso", default="canal-de-denuncia")
    ver.add_argument("--modelo", action="append", default=None)
    ver.add_argument("--ultimas", type=int, default=1, help="quantas execucoes por modelo")

    listar = comandos.add_parser("listar", help="lista modelos e execucoes")
    listar.add_argument("--caso", default=None)

    painel = comandos.add_parser("painel", help="abre o painel local (Streamlit)")
    painel.add_argument("--porta", type=int, default=8501)

    hold = comandos.add_parser(
        "holdout", help="valida o holdout escrito a mao, ou cria o arquivo inicial"
    )
    hold.add_argument("--caso", default="canal-de-denuncia")
    hold.add_argument(
        "--iniciar",
        action="store_true",
        help="cria o arquivo vazio com o esquema e as instrucoes, se ainda nao existir",
    )
    hold.add_argument("--autor", action="append", default=None, help="repetivel")

    dash = comandos.add_parser("dashboard", help="exporta o dashboard estatico em HTML")
    dash.add_argument("--caso", default="canal-de-denuncia")
    dash.add_argument("--destino", type=Path, default=None)

    return principal


def _plano(argumentos: argparse.Namespace, apelido: str) -> Plano:
    return Plano(
        caso=argumentos.caso,
        modelo=apelido,
        fonte=argumentos.fonte,
        ajustes=Ajustes(
            limiar_booleano=argumentos.limiar_booleano,
            limiar_de_risco=argumentos.limiar_de_risco,
            dispositivo=argumentos.dispositivo,
            maquina=argumentos.maquina,
        ),
        repeticoes=argumentos.repeticoes,
        limite=None if argumentos.limite == 0 else argumentos.limite,
        cenarios=tuple(argumentos.cenario or ()),
        registros=tuple(argumentos.registro or ()),
        concorrencia=argumentos.concorrencia,
        tracos=argumentos.tracos,
        atras=argumentos.atras,
    )


def _modelos_pedidos(argumentos: argparse.Namespace) -> list[str]:
    if argumentos.comparar:
        disponiveis = [nome for nome, m in CATALOGO.items() if m.tem_chave]
        if not disponiveis:
            raise SystemExit(
                "Nenhuma chave de API definida. Copie .env.example para .env e preencha."
            )
        sem_chave = [nome for nome in CATALOGO if nome not in disponiveis]
        if sem_chave:
            console.print(f"[yellow]Sem chave, fora da comparacao: {', '.join(sem_chave)}[/yellow]")
        return disponiveis
    return argumentos.modelo or ["jev"]


def _rodar(argumentos: argparse.Namespace) -> int:
    execucoes = []
    for apelido in _modelos_pedidos(argumentos):
        console.rule(apelido)
        try:
            execucao = asyncio.run(
                executar(_plano(argumentos, apelido), progresso=lambda linha: console.print(linha))
            )
        except (RuntimeError, KeyError, FileNotFoundError) as erro:
            console.print(f"[red]{apelido}: {erro}[/red]")
            continue
        relatorio.imprimir(execucao, console)
        if not argumentos.nao_salvar:
            destino = escrever_execucao(execucao)
            console.print(f"[dim]gravado em {destino.relative_to(Path.cwd())}[/dim]")
        execucoes.append(execucao)

    if len(execucoes) > 1:
        console.rule("comparacao")
        relatorio.comparar(execucoes, console)
    return 0 if execucoes else 1


def _comparar(argumentos: argparse.Namespace) -> int:
    escolhidas: list[Execucao] = []
    modelos = argumentos.modelo or sorted(
        {caminho.parent.name for caminho in execucoes_existentes(argumentos.caso)}
    )
    for apelido in modelos:
        caminhos = execucoes_existentes(argumentos.caso, apelido)[: argumentos.ultimas]
        escolhidas.extend(carregar_execucao(caminho) for caminho in caminhos)
    if not escolhidas:
        console.print("Nenhuma execucao gravada ainda. Rode `lab rodar` primeiro.")
        return 1
    relatorio.comparar(escolhidas, console)
    return 0


def _listar(argumentos: argparse.Namespace) -> int:
    console.print("[bold]Modelos[/bold]")
    for nome, escolhido in CATALOGO.items():
        if escolhido.local:
            marca = "[green]local, sem chave[/green]"
        elif escolhido.tem_chave:
            marca = "[green]chave ok[/green]"
        else:
            marca = "[yellow]sem chave[/yellow]"
        console.print(f"  {nome:9} {escolhido.id_na_rota:38} {escolhido.papel:18} {marca}")
    console.print("\n[bold]Execucoes gravadas[/bold]")
    caminhos = execucoes_existentes(argumentos.caso)
    if not caminhos:
        console.print("  nenhuma")
    for caminho in caminhos[:30]:
        console.print(f"  {caminho.parent.parent.name}/{caminho.parent.name}/{caminho.stem}")
    return 0


def _painel(argumentos: argparse.Namespace) -> int:
    app = Path(__file__).resolve().parent / "painel" / "app.py"
    console.print(f"Abrindo o painel em http://localhost:{argumentos.porta}")
    try:
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app),
                "--server.port",
                str(argumentos.porta),
            ]
        )
    except FileNotFoundError:  # pragma: no cover - depends on the environment
        console.print("[red]Streamlit nao esta instalado. Rode `uv sync --extra painel`.[/red]")
        return 1


def _dashboard(argumentos: argparse.Namespace) -> int:
    from lab.dashboard import exportar

    destino = exportar(argumentos.caso, argumentos.destino)
    console.print(f"Dashboard em {destino}")
    return 0


def _holdout(argumentos: argparse.Namespace) -> int:
    from lab import holdout
    from lab.casos import carregar_caso

    caminho = carregar_caso(argumentos.caso).holdout
    if argumentos.iniciar:
        if caminho.is_file():
            console.print(f"[yellow]{caminho} ja existe; nada a fazer.[/yellow]")
        else:
            documento = holdout.modelo_de_arquivo(argumentos.caso, argumentos.autor)
            holdout.escrever(documento, argumentos.caso)
            console.print(f"Arquivo iniciado em {caminho}")
            for instrucao in documento["instrucoes"]:
                console.print(f"  [dim]- {instrucao}[/dim]")
            return 0

    documento = holdout.carregar(argumentos.caso)
    relatorio = holdout.validar(documento, argumentos.caso)

    console.print(f"[bold]{caminho}[/bold]")
    console.print(f"  {relatorio.distribuicao}")
    for problema in relatorio.erros:
        console.print(f"  [red]{problema}[/red]")
    for problema in relatorio.avisos:
        console.print(f"  [yellow]{problema}[/yellow]")
    if relatorio.valido and not relatorio.avisos:
        console.print("  [green]sem problemas[/green]")
    return 0 if relatorio.valido else 1


def main() -> int:
    """Entry point for the ``lab`` command."""
    load_dotenv()
    argumentos = _analisador().parse_args()
    acoes = {
        "rodar": _rodar,
        "comparar": _comparar,
        "listar": _listar,
        "painel": _painel,
        "dashboard": _dashboard,
        "holdout": _holdout,
    }
    if argumentos.comando == "rodar" and not os.getenv("TYPESAFE_API_KEY"):
        console.print(
            "[yellow]TYPESAFE_API_KEY nao definida: o Jev nao vai rodar. "
            "Os baselines precisam de OPENROUTER_API_KEY.[/yellow]"
        )
    return acoes[argumentos.comando](argumentos)


if __name__ == "__main__":
    raise SystemExit(main())
