"""Run one model over one dataset and write the result file.

The loop is Pydantic Evals': it runs the cases concurrently and scores the evaluators. What
it does not do is keep the trace of each run, the recovered probabilities or the cost, so
the task function collects those as it goes and they are merged into the result afterwards.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic_evals import Case, Dataset
from pydantic_evals.dataset import increment_eval_metric

from lab import holdout
from lab.casos import carregar_caso
from lab.confianca import reler_com_limiares
from lab.custo import Custo, custo_de_maquina, custo_de_uso
from lab.metricas import AcertoDeSinal, CapturouNivel3, UrgenciaComposta, agregar
from lab.modelos import Ajustes, modelo
from lab.precos import carregar_precos
from lab.resultados import Execucao, ResultadoDeCaso, ambiente_atual, novo_id
from lab.tracos import extrair_traco

__all__ = ["Plano", "carregar_dataset", "executar", "selecionar"]


@dataclass
class Plano:
    """Everything that decides what a run does. Recorded whole in the result file."""

    caso: str = "canal-de-denuncia"
    modelo: str = "jev"
    fonte: str = "dataset"
    """``dataset`` for the synthetic corpus, ``holdout`` for the hand-written one."""

    ajustes: Ajustes = field(default_factory=Ajustes)
    repeticoes: int = 3
    """Repeated with identical input, because a single pass publishes noise as difference."""

    limite: int | None = 40
    """How many cases to draw. ``None`` runs the whole dataset - 1120 cases times the
    repetitions, which is real money on a frontier model."""

    semente_da_amostra: int = 7
    cenarios: tuple[str, ...] = ()
    registros: tuple[str, ...] = ()
    concorrencia: int = 4
    tracos: str = "amostra"
    """``amostra`` keeps the full trace for the first few cases and every failure,
    ``todos`` keeps all of them, ``nenhum`` keeps none. Keeping every trace of a full run
    would put hundreds of megabytes of message history in a versioned repository."""

    amostra_de_tracos: int = 12
    arquivos_de_precos: tuple[str, ...] = ()
    atras: str | None = None
    """A model to put behind this one as a fallback, for the hand-off measurement."""

    def para_registro(self) -> dict[str, Any]:
        return {
            "fonte": self.fonte,
            "limite": self.limite,
            "semente_da_amostra": self.semente_da_amostra,
            "cenarios": list(self.cenarios),
            "registros": list(self.registros),
            "concorrencia": self.concorrencia,
            "tracos": self.tracos,
            "atras": self.atras,
        }


def carregar_dataset(caso: str, fonte: str = "dataset") -> dict[str, Any]:
    """Read a case's corpus from disk, refusing one that cannot produce a fair number.

    The holdout is validated before it is used, not after. Its errors are the kind that do
    not announce themselves in a metric - a label that disagrees with the composition rule,
    or a case copied from the grammar - and a run that starts anyway spends money to
    produce a number nobody should trust.

    Raises:
        FileNotFoundError: Naming the holdout explicitly, since its absence is expected
            until it is written by hand and is not a bug to debug.
        ValueError: If the holdout is empty or fails validation, listing what is wrong.
    """
    carregado = carregar_caso(caso)
    caminho = carregado.dataset if fonte == "dataset" else carregado.holdout
    if not caminho.is_file():
        if fonte == "holdout":
            raise FileNotFoundError(
                f"{caminho} ainda nao existe. O holdout e escrito e rotulado a mao, por "
                f"definicao: se fosse gerado, nao seria holdout. Comece com "
                f"`lab holdout --iniciar`, ou pela aba Holdout do painel. "
                f"Ver docs/metodologia.md."
            )
        raise FileNotFoundError(f"{caminho} nao existe. Rode gerar.py primeiro.")

    documento: dict[str, Any] = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    if fonte == "holdout":
        documento = holdout.normalizar(documento)
        if not documento["casos"]:
            raise ValueError(
                f"{caminho} existe mas nao tem nenhum caso escrito. O holdout e trabalho "
                f"manual: sao {holdout.TAMANHO_ALVO} relatos escritos e rotulados a mao."
            )
        relatorio = holdout.validar(documento, caso)
        if not relatorio.valido:
            erros = "\n  ".join(str(p) for p in relatorio.erros)
            raise ValueError(f"{caminho} nao passou na validacao:\n  {erros}")
    documento["arquivo"] = caminho.name
    return documento


def selecionar(documento: dict[str, Any], plano: Plano) -> list[dict[str, Any]]:
    """Draw the subset to run, keeping the class balance of the whole.

    A plain random subset of a balanced corpus is not balanced, and a recall of level 3
    computed over nine level 3 cases is not a number worth publishing. The draw is
    stratified by label and seeded, so two models are compared on the same cases.
    """
    casos = documento["casos"]
    if plano.cenarios:
        casos = [c for c in casos if c["cenario"] in plano.cenarios]
    if plano.registros:
        casos = [c for c in casos if c["registro"] in plano.registros]
    if plano.limite is None or plano.limite >= len(casos):
        return list(casos)

    por_nivel: dict[Any, list[dict[str, Any]]] = {}
    for caso in casos:
        por_nivel.setdefault(caso["rotulo"]["urgencia"], []).append(caso)

    rng = random.Random(plano.semente_da_amostra)
    escolhidos: list[dict[str, Any]] = []
    niveis = sorted(por_nivel, key=lambda n: (n is None, n))
    por_grupo = max(1, plano.limite // len(niveis))
    for nivel in niveis:
        disponiveis = por_nivel[nivel]
        escolhidos.extend(rng.sample(disponiveis, min(por_grupo, len(disponiveis))))
    # Any remainder goes to whichever cases are left, still deterministically.
    restantes = [c for c in casos if c not in escolhidos]
    faltam = plano.limite - len(escolhidos)
    if faltam > 0 and restantes:
        escolhidos.extend(rng.sample(restantes, min(faltam, len(restantes))))
    escolhidos.sort(key=lambda c: c["id"])
    return escolhidos


async def executar(plano: Plano, progresso: Callable[[str], None] | None = None) -> Execucao:
    """Run the plan and return the finished run, metrics included.

    Args:
        plano: What to run.
        progresso: Called with a short line at each milestone, for a CLI or a panel.

    Returns:
        The run. Writing it to disk is the caller's call - the panel shows a run before
        deciding to keep it.
    """
    avisar = progresso or (lambda _: None)
    carregado = carregar_caso(plano.caso)
    agente_do_caso = carregado.modulo("agente")
    tipos = carregado.modulo("tipos")

    documento = carregar_dataset(plano.caso, plano.fonte)
    selecionados = selecionar(documento, plano)
    tabela = carregar_precos(*[Path(a) for a in plano.arquivos_de_precos])
    escolhido = modelo(plano.modelo)
    agente = agente_do_caso.construir_agente(plano.modelo, plano.ajustes)
    if plano.atras is not None:
        from lab.modelos import construir

        agente = agente_do_caso.construir_agente(plano.modelo, plano.ajustes)
        agente.model = construir(plano.modelo, plano.ajustes, atras=plano.atras)

    avisar(
        f"{len(selecionados)} casos x {plano.repeticoes} repeticoes em {plano.modelo} "
        f"({escolhido.id_na_rota})"
    )

    versoes: set[str] = set()

    async def tarefa(texto: str) -> dict[str, Any]:
        """Run the agent on one report and record everything the metrics will need."""
        inicio = time.perf_counter()
        resultado = await agente.run(texto)
        duracao = (time.perf_counter() - inicio) * 1000

        saida = resultado.output
        traco = extrair_traco(resultado.all_messages())
        sinais = tipos.Sinais.model_validate(saida.model_dump())
        composicao = tipos.compor_urgencia(sinais)

        releitura = reler_com_limiares(
            valores=saida.model_dump(),
            confiancas=traco.confianca,
            limiar_original=plano.ajustes.limiar_booleano,
            limiar_novo=plano.ajustes.limiar_de_risco,
            campos=plano.ajustes.campos_de_risco,
        )
        uso = resultado.usage
        increment_eval_metric("tokens_de_entrada", uso.input_tokens or 0)
        increment_eval_metric("tokens_de_saida", uso.output_tokens or 0)
        increment_eval_metric("requisicoes", traco.requisicoes)

        for passo in traco.passos:
            if passo.modelo:
                versoes.add(passo.modelo)

        return {
            "saida": saida,
            "sinais": saida.model_dump(mode="json"),
            "urgencia_composta": None if composicao.urgencia is None else int(composicao.urgencia),
            "regra": composicao.regra,
            "urgencia_direta": int(saida.urgencia_direta),
            "traco": traco,
            "latencia_ms": duracao,
            "uso": uso,
            "releitura": releitura,
        }

    casos_de_avaliacao: list[Case[str, Any, dict[str, Any]]] = []
    for repeticao in range(1, plano.repeticoes + 1):
        for caso in selecionados:
            casos_de_avaliacao.append(
                Case(
                    name=f"{caso['id']}#r{repeticao}",
                    inputs=caso["texto"],
                    metadata={
                        "caso_id": caso["id"],
                        "repeticao": repeticao,
                        "cenario": caso["cenario"],
                        "registro": caso["registro"],
                        "urgencia": caso["rotulo"]["urgencia"],
                        "sinais": caso["rotulo"]["sinais"],
                        "sinais_ambiguos": caso["rotulo"]["sinais_ambiguos"],
                    },
                )
            )

    conjunto = Dataset[str, Any, dict[str, Any]](
        name=f"{plano.caso}/{plano.fonte}",
        cases=casos_de_avaliacao,
        evaluators=[CapturouNivel3(), UrgenciaComposta(), AcertoDeSinal()],
    )

    execucao = Execucao(
        id=novo_id(plano.modelo),
        caso=plano.caso,
        modelo=plano.modelo,
        modelo_id=escolhido.id_na_rota,
        modelo_versao_reportada=None,
        rota=escolhido.rota,
        dataset={
            "arquivo": documento["arquivo"],
            "semente": documento.get("semente"),
            "gramatica_hash": documento.get("gramatica_hash"),
            "total_no_arquivo": len(documento["casos"]),
            "selecionados": len(selecionados),
        },
        precos={
            "arquivos": list(tabela.arquivos),
            "coletado_em": list(tabela.coletado_em),
            "cambio_usd_brl": tabela.cambio_usd_brl,
            "fonte_do_cambio": tabela.fonte_do_cambio,
        },
        ajustes=plano.ajustes.para_registro() | plano.para_registro(),
        repeticoes=plano.repeticoes,
        subconjunto={"ids": [c["id"] for c in selecionados]},
        inicio=datetime.now(UTC).isoformat(),
        ambiente=ambiente_atual(),
    )

    semaforo = asyncio.Semaphore(plano.concorrencia)
    esperados = {c["id"]: c for c in selecionados}

    async def envelope(texto: str) -> dict[str, Any]:
        async with semaforo:
            return await tarefa(texto)

    # The wall clock of the evaluation, which is what a machine-priced model is billed
    # for. Not the sum of the per-case latencies: with concurrency those overlap, and
    # adding them up would bill every worker separately.
    relogio = time.perf_counter()
    relatorio_de_avaliacao = await conjunto.evaluate(
        envelope, max_concurrency=plano.concorrencia, name=execucao.id
    )
    segundos_de_parede = time.perf_counter() - relogio

    custo_total = Custo.zero()
    guardados = 0
    for indice, linha in enumerate(relatorio_de_avaliacao.cases):
        metadados = linha.metadata or {}
        fonte = esperados[metadados["caso_id"]]
        saida = linha.output
        traco = saida["traco"]
        uso = saida["uso"]
        # A local model spends no tokens; it spends machine time, and that is priced once
        # for the whole run below, against the wall clock.
        custo = (
            Custo.zero()
            if escolhido.id_de_preco is None
            else custo_de_uso(
                uso.input_tokens or 0, uso.output_tokens or 0, escolhido.id_de_preco, tabela
            )
        )
        custo_total = custo_total + custo

        guardar_traco = plano.tracos == "todos" or (
            plano.tracos == "amostra" and guardados < plano.amostra_de_tracos
        )
        if guardar_traco:
            guardados += 1

        modelos_vistos = {p.modelo for p in traco.passos if p.modelo}
        resultado = ResultadoDeCaso(
            caso_id=metadados["caso_id"],
            repeticao=metadados["repeticao"],
            cenario=metadados["cenario"],
            registro=metadados["registro"],
            esperado={
                "sinais": fonte["rotulo"]["sinais"],
                "urgencia": fonte["rotulo"]["urgencia"],
                "sinais_ambiguos": fonte["rotulo"]["sinais_ambiguos"],
            },
            obtido=saida["sinais"],
            urgencia_esperada=fonte["rotulo"]["urgencia"],
            urgencia_composta=saida["urgencia_composta"],
            urgencia_direta=saida["urgencia_direta"],
            regra=saida["regra"],
            confianca=traco.confianca,
            probabilidades=traco.probabilidades,
            probabilidades_booleanas=saida["releitura"].probabilidades,
            releitura_de_risco=_releitura_em_dicionario(saida, tipos),
            acertos={
                nome.removeprefix("sinal_"): resultado_da_asercao.value
                for nome, resultado_da_asercao in linha.assertions.items()
                if nome.startswith("sinal_")
            },
            latencia_ms=round(saida["latencia_ms"], 1),
            tokens_de_entrada=uso.input_tokens or 0,
            tokens_de_saida=uso.output_tokens or 0,
            requisicoes=traco.requisicoes,
            chamadas_de_tool=traco.chamadas_de_tool,
            custo_usd=custo.dolares,
            custo_brl=custo.reais,
            handoff=bool(modelos_vistos - {escolhido.id_na_rota}) if plano.atras else False,
            traco=_traco_em_dicionario(traco) if guardar_traco else None,
        )
        execucao.casos.append(resultado)
        if indice == 0:
            execucao.modelo_versao_reportada = next(iter(sorted(modelos_vistos)), None)

    for falha in relatorio_de_avaliacao.failures:
        metadados = falha.metadata or {}
        execucao.casos.append(
            ResultadoDeCaso(
                caso_id=metadados.get("caso_id", falha.name),
                repeticao=metadados.get("repeticao", 0),
                cenario=metadados.get("cenario", ""),
                registro=metadados.get("registro", ""),
                esperado={"urgencia": metadados.get("urgencia")},
                urgencia_esperada=metadados.get("urgencia"),
                erro=f"{falha.error_message}",
            )
        )

    if escolhido.local:
        custo_total = custo_de_maquina(
            segundos_de_parede, plano.ajustes.maquina or "local-proprio", tabela
        )
        # Split evenly across the cases the machine was held for, so a per-case cost exists
        # and sums back to the run's cost.
        avaliados = [resultado for resultado in execucao.casos if resultado.erro is None]
        if avaliados:
            por_caso_usd = custo_total.dolares / len(avaliados)
            por_caso_brl = custo_total.reais / len(avaliados)
            for resultado in avaliados:
                resultado.custo_usd = por_caso_usd
                resultado.custo_brl = por_caso_brl

    execucao.fim = datetime.now(UTC).isoformat()
    execucao.duracao_s = round(
        (
            datetime.fromisoformat(execucao.fim) - datetime.fromisoformat(execucao.inicio)
        ).total_seconds(),
        2,
    )
    execucao.metricas = agregar(execucao.casos, custo_total, segundos_de_parede)
    execucao.metricas["maquina"] = (
        {
            "nome": plano.ajustes.maquina or "local-proprio",
            "usd_por_hora": tabela.maquina(plano.ajustes.maquina or "local-proprio").usd_por_hora,
            "dispositivo": plano.ajustes.dispositivo,
            "nota": (
                "O relogio de parede da execucao inclui a carga fria do checkpoint, que um "
                "servico longo amortiza. Para uma execucao curta, este custo e pessimista."
            ),
        }
        if escolhido.local
        else None
    )
    avisar(
        f"recall nivel 3: {execucao.metricas['recall_nivel_3']} | "
        f"custo US$ {execucao.metricas['custo_usd_por_mil']}/mil"
    )
    return execucao


def _releitura_em_dicionario(saida: dict[str, Any], tipos: Any) -> dict[str, Any]:
    """What the lower risk bar changed, and the level the reread signals compose to."""
    releitura = saida["releitura"]
    if not releitura.valores:
        return {}
    ajustados = {**saida["sinais"], **releitura.valores}
    composicao = tipos.compor_urgencia(tipos.Sinais.model_validate(ajustados))
    return {
        "mudaram": list(releitura.mudaram),
        "valores": releitura.valores,
        "urgencia_composta": None if composicao.urgencia is None else int(composicao.urgencia),
        "regra": composicao.regra,
    }


def _traco_em_dicionario(traco: Any) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(traco)
