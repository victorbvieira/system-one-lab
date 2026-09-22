"""Streamlit panel: pick the models, run them, and inspect step by step what happened.

Three screens, in the order the work actually happens: configure, run, read. The reading
screen is the reason this exists - a metric tells you a model is worse, and only the trace
tells you why. It shows, per case, the report as the model saw it, each signal with the
confidence behind it, and every step of the run including the tools that were called.

The dashboard screen embeds the very same HTML file that gets exported and committed, so
what is reviewed here and what gets published cannot drift apart.

Run it with ``uv run lab painel``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from lab.casos import carregar_caso, casos_disponiveis
from lab.dashboard import exportar, ultimas_execucoes
from lab.execucao import Plano, carregar_dataset
from lab.execucao import executar as executar_plano
from lab.modelos import CATALOGO, Ajustes
from lab.precos import carregar_precos
from lab.resultados import (
    Execucao,
    ResultadoDeCaso,
    carregar_execucao,
    escrever_execucao,
    execucoes_existentes,
)

st.set_page_config(page_title="system-one-lab", page_icon="•", layout="wide")
load_dotenv()

NIVEIS = {0: "0 rotina", 1: "1 relevante", 2: "2 grave", 3: "3 critico", None: "indeterminado"}


def _rotulo_de_nivel(valor: int | None) -> str:
    return NIVEIS.get(valor, str(valor))


# -- configure and run -------------------------------------------------------------


def tela_de_configuracao() -> None:
    """Choose the models and the settings, and run."""
    st.subheader("Configuracao da execucao")

    casos = casos_disponiveis()
    if not casos:
        st.error("Nenhum caso encontrado em casos/.")
        return

    coluna_esquerda, coluna_direita = st.columns(2)
    with coluna_esquerda:
        caso = st.selectbox("Caso", casos)
        fonte = st.radio(
            "Corpus",
            ["dataset", "holdout"],
            horizontal=True,
            help=(
                "O sintetico mede se a abordagem funciona e serve para iterar rapido. "
                "A metrica que vai no artigo e a do holdout, escrito e rotulado a mao."
            ),
        )
        com_chave = [nome for nome, m in CATALOGO.items() if m.tem_chave]
        sem_chave = [nome for nome in CATALOGO if nome not in com_chave]
        escolhidos = st.multiselect(
            "Modelos",
            list(CATALOGO),
            default=com_chave[:1] or ["jev"],
            format_func=lambda nome: (
                f"{nome} — {CATALOGO[nome].papel}"
                + (" · roda nesta maquina" if CATALOGO[nome].local else "")
            ),
        )
        if sem_chave:
            st.caption(f"Sem chave no ambiente: {', '.join(sem_chave)}")
        if any(CATALOGO[nome].local for nome in escolhidos):
            st.info(
                "Modelo local selecionado: o relato nao sai desta maquina. E a unica rota "
                "do catalogo que um dia poderia ler denuncia real sem decisao de "
                "compliance sobre mandar texto para terceiro."
            )
        atras = st.selectbox(
            "Modelo atras (FallbackModel)",
            ["nenhum", *CATALOGO],
            help=(
                "Mede a taxa de hand-off. Um arranjo que entrega quase tudo ao modelo caro "
                "paga as duas contas e fica mais lento que nao usar o System One."
            ),
        )

    with coluna_direita:
        repeticoes = st.slider(
            "Repeticoes",
            1,
            10,
            3,
            help=(
                "Chamada repetida com entrada identica move as probabilidades em alguns "
                "centesimos. Sem repeticao, publica-se ruido como diferenca."
            ),
        )
        limite = st.number_input(
            "Casos por execucao (0 = dataset inteiro)", min_value=0, max_value=5000, value=40
        )
        concorrencia = st.slider("Concorrencia", 1, 16, 4)
        tracos = st.radio("Guardar tracos", ["amostra", "todos", "nenhum"], horizontal=True)
        coluna_local_a, coluna_local_b = st.columns(2)
        dispositivo = coluna_local_a.selectbox(
            "Dispositivo (modelo local)",
            ["automatico", "cpu", "cuda"],
            help="Sem GPU no container, 'cuda' falha ao carregar o checkpoint.",
        )
        maquinas = sorted(carregar_precos().maquinas)
        maquina = coluna_local_b.selectbox(
            "Maquina para precificar (modelo local)",
            maquinas,
            index=maquinas.index("local-proprio") if "local-proprio" in maquinas else 0,
            help=(
                "Um modelo local nao tem preco por token: tem preco por hora, que corre "
                "parado. O padrao e hardware ja pago, de custo marginal zero."
            ),
        )

    with st.expander("Ajustes do agente"):
        agente = carregar_caso(caso).modulo("agente")
        instrucoes = st.text_area(
            "Instrucoes (identicas para todos os modelos, senao a comparacao mede o arranjo)",
            value=agente.INSTRUCOES_PADRAO,
            height=150,
        )
        coluna_a, coluna_b = st.columns(2)
        limiar_booleano = coluna_a.slider(
            "Limiar booleano",
            0.05,
            0.95,
            0.5,
            0.05,
            help="Onde um sim/nao do System One vira True.",
        )
        limiar_de_risco = coluna_b.slider(
            "Limiar dos campos de risco",
            0.05,
            0.95,
            0.3,
            0.05,
            help=(
                "Mais baixo de proposito: um falso negativo em nivel 3 custa muito mais "
                "que um falso positivo. Aplicado depois da resposta, sem segunda chamada."
            ),
        )

    documento = carregar_dataset(caso, fonte) if _existe(caso, fonte) else None
    if documento:
        cenarios = sorted({c["cenario"] for c in documento["casos"]})
        registros = sorted({c["registro"] for c in documento["casos"]})
        coluna_c, coluna_d = st.columns(2)
        filtro_de_cenario = coluna_c.multiselect("Filtrar cenarios", cenarios)
        filtro_de_registro = coluna_d.multiselect("Filtrar registros", registros)
    else:
        st.warning(f"O corpus '{fonte}' ainda nao existe para este caso.")
        filtro_de_cenario, filtro_de_registro = [], []

    salvar = st.checkbox("Gravar em resultados/ ao terminar", value=True)

    if st.button("Rodar", type="primary", disabled=not escolhidos or documento is None):
        for apelido in escolhidos:
            plano = Plano(
                caso=caso,
                modelo=apelido,
                fonte=fonte,
                ajustes=Ajustes(
                    limiar_booleano=limiar_booleano,
                    limiar_de_risco=limiar_de_risco,
                    instrucoes=instrucoes,
                    dispositivo=None if dispositivo == "automatico" else dispositivo,
                    maquina=maquina,
                ),
                repeticoes=repeticoes,
                limite=None if limite == 0 else int(limite),
                cenarios=tuple(filtro_de_cenario),
                registros=tuple(filtro_de_registro),
                concorrencia=concorrencia,
                tracos=tracos,
                atras=None if atras == "nenhum" else atras,
            )
            with st.status(f"Rodando {apelido}...", expanded=True) as estado:
                try:
                    execucao = asyncio.run(executar_plano(plano, progresso=st.write))
                except Exception as erro:  # a falha do provedor vai inteira para quem operou
                    estado.update(label=f"{apelido}: falhou", state="error")
                    st.exception(erro)
                    continue
                if salvar:
                    destino = escrever_execucao(execucao)
                    st.write(f"gravado em `{destino}`")
                estado.update(label=f"{apelido}: {execucao.id}", state="complete")
            _cartoes_de_metrica(execucao)


def _existe(caso: str, fonte: str) -> bool:
    carregado = carregar_caso(caso)
    return (carregado.dataset if fonte == "dataset" else carregado.holdout).is_file()


def _cartoes_de_metrica(execucao: Execucao) -> None:
    metricas = execucao.metricas
    colunas = st.columns(5)
    colunas[0].metric("Recall nivel 3", _percentual(metricas.get("recall_nivel_3")))
    colunas[1].metric("Acuracia composta", _percentual(metricas.get("acuracia_composta")))
    colunas[2].metric("Acuracia do campo direto", _percentual(metricas.get("acuracia_direta")))
    colunas[3].metric("US$ / mil", f"{metricas.get('custo_usd_por_mil', 0):.4f}")
    colunas[4].metric("p95", f"{metricas.get('latencia_p95_ms', 0):.0f} ms")
    if vazao := metricas.get("triagens_por_hora"):
        maquina = metricas.get("maquina")
        nota = f" · {maquina['nome']} a US$ {maquina['usd_por_hora']}/h" if maquina else ""
        st.caption(f"Vazao medida: {vazao:.0f} triagens por hora{nota}")


def _percentual(valor: float | None) -> str:
    return "nao reportado" if valor is None else f"{valor * 100:.1f}%"


# -- read a run --------------------------------------------------------------------


def tela_de_execucoes() -> None:
    """Open one run and read it, case by case, step by step."""
    st.subheader("Execucoes gravadas")
    caminhos = execucoes_existentes()
    if not caminhos:
        st.info("Nenhuma execucao gravada. Rode uma na aba de configuracao.")
        return

    escolhido = st.selectbox(
        "Execucao",
        caminhos,
        format_func=lambda p: f"{p.parent.parent.name} / {p.parent.name} / {p.stem}",
    )
    execucao = carregar_execucao(Path(escolhido))

    st.caption(
        f"{execucao.modelo_id} respondeu `{execucao.modelo_versao_reportada}` · "
        f"precos {', '.join(execucao.precos['arquivos'])} · "
        f"{execucao.dataset['selecionados']} casos · {execucao.repeticoes} repeticoes · "
        f"commit `{execucao.ambiente.get('commit')}`"
    )
    _cartoes_de_metrica(execucao)

    aba_casos, aba_metricas, aba_ajustes = st.tabs(["Casos", "Metricas", "Ajustes"])

    with aba_casos:
        _inspecionar_casos(execucao)
    with aba_metricas:
        st.json(execucao.metricas)
    with aba_ajustes:
        st.json(execucao.ajustes | {"ambiente": execucao.ambiente})


def _inspecionar_casos(execucao: Execucao) -> None:
    somente_erros = st.checkbox("So os casos em que o modelo errou a urgencia")
    casos = [
        caso
        for caso in execucao.casos
        if not somente_erros or caso.urgencia_composta != caso.urgencia_esperada
    ]
    if not casos:
        st.info("Nenhum caso com esse filtro.")
        return

    st.dataframe(
        [
            {
                "caso": caso.caso_id,
                "rep": caso.repeticao,
                "cenario": caso.cenario,
                "registro": caso.registro,
                "esperado": _rotulo_de_nivel(caso.urgencia_esperada),
                "composto": _rotulo_de_nivel(caso.urgencia_composta),
                "direto": _rotulo_de_nivel(caso.urgencia_direta),
                "acertou": caso.urgencia_composta == caso.urgencia_esperada,
                "ms": caso.latencia_ms,
                "US$": round(caso.custo_usd, 6),
                "traco": caso.traco is not None,
            }
            for caso in casos
        ],
        use_container_width=True,
        hide_index=True,
    )

    escolhido = st.selectbox(
        "Abrir caso",
        range(len(casos)),
        format_func=lambda i: f"{casos[i].caso_id} (rep {casos[i].repeticao})",
    )
    _detalhe_do_caso(execucao, casos[escolhido])


def _detalhe_do_caso(execucao: Execucao, caso: ResultadoDeCaso) -> None:
    if caso.erro:
        st.error(caso.erro)

    texto = _texto_do_caso(execucao.caso, execucao.ajustes.get("fonte", "dataset"), caso.caso_id)
    if texto:
        st.markdown("**O relato, como o modelo o recebeu**")
        st.text_area("relato", texto, height=160, label_visibility="collapsed")

    esperados = caso.esperado.get("sinais") or {}
    ambiguos = set(caso.esperado.get("sinais_ambiguos") or [])
    st.markdown("**Sinais**")
    st.dataframe(
        [
            {
                "sinal": nome,
                "esperado": "ambiguo" if nome in ambiguos else esperados.get(nome),
                "obtido": caso.obtido.get(nome),
                "acertou": caso.acertos.get(nome),
                "confianca": caso.confianca.get(nome),
                "probabilidade de sim": caso.probabilidades_booleanas.get(nome),
            }
            for nome in esperados
        ],
        use_container_width=True,
        hide_index=True,
    )

    colunas = st.columns(4)
    colunas[0].metric("Esperado", _rotulo_de_nivel(caso.urgencia_esperada))
    colunas[1].metric("Composto dos sinais", _rotulo_de_nivel(caso.urgencia_composta))
    colunas[2].metric("Perguntado direto", _rotulo_de_nivel(caso.urgencia_direta))
    colunas[3].metric("Regra", caso.regra or "—")

    if caso.releitura_de_risco.get("mudaram"):
        st.info(
            f"Com o limiar de risco, mudaram: "
            f"{', '.join(caso.releitura_de_risco['mudaram'])}. "
            f"A urgencia passaria a ser "
            f"{_rotulo_de_nivel(caso.releitura_de_risco.get('urgencia_composta'))}."
        )

    if caso.probabilidades:
        with st.expander("Distribuicao de probabilidades por opcao"):
            st.json(caso.probabilidades)

    st.markdown("**Passos**")
    if caso.traco is None:
        st.caption(
            "O traco deste caso nao foi guardado. Rode com 'todos' para guardar todos — "
            "guardar o historico de mensagens de uma execucao inteira poe centenas de "
            "megabytes num repositorio versionado."
        )
        return

    traco = caso.traco
    st.caption(
        f"{traco['requisicoes']} requisicao(oes) · "
        f"tools chamadas: {', '.join(traco['chamadas_de_tool']) or 'nenhuma'}"
    )
    for passo in traco["passos"]:
        titulo = f"{passo['indice']}. {passo['origem']}"
        if passo.get("modelo"):
            titulo += f" — {passo['modelo']}"
        if passo.get("tokens_de_entrada") is not None:
            titulo += f" · {passo['tokens_de_entrada']} entrada / {passo['tokens_de_saida']} saida"
        with st.expander(titulo):
            for parte in passo["partes"]:
                st.markdown(f"*{parte['tipo']}*")
                if parte["tipo"] == "chamada_de_tool":
                    st.code(parte["conteudo"], language="text")
                    st.json(parte["detalhes"].get("argumentos"))
                else:
                    st.text(parte["conteudo"][:4000])
            if passo.get("detalhes_do_provedor"):
                st.json(passo["detalhes_do_provedor"])


@st.cache_data(show_spinner=False)
def _textos_do_corpus(caso: str, fonte: str) -> dict[str, str]:
    try:
        documento = carregar_dataset(caso, fonte)
    except FileNotFoundError:
        return {}
    return {c["id"]: c["texto"] for c in documento["casos"]}


def _texto_do_caso(caso: str, fonte: str, caso_id: str) -> str | None:
    return _textos_do_corpus(caso, fonte).get(caso_id)


# -- dashboard ---------------------------------------------------------------------


def tela_de_dashboard() -> None:
    """The exported dashboard, embedded as-is."""
    st.subheader("Dashboard")
    casos = sorted({p.parent.parent.name for p in execucoes_existentes()})
    if not casos:
        st.info("Nenhuma execucao gravada ainda.")
        return
    caso = st.selectbox("Caso", casos)
    execucoes = ultimas_execucoes(caso)
    st.caption(
        "Ultima execucao de cada modelo: " + ", ".join(f"{e.modelo} ({e.id})" for e in execucoes)
    )
    if st.button("Exportar para resultados/ e commitar depois"):
        destino = exportar(caso)
        st.success(f"Gravado em {destino}")

    pagina = exportar(caso, _temporario(caso))
    st.components.v1.html(pagina.read_text(encoding="utf-8"), height=2400, scrolling=True)


def _temporario(caso: str) -> Path:
    destino = Path(st.session_state.get("tmp", "/tmp")) / f"dashboard-{caso}.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino


def principal() -> None:
    st.title("system-one-lab")
    st.caption(
        "Um modelo System One contra LLMs de fronteira, em decisoes tipadas. "
        "Dataset pequeno, dominio unico, rotulagem de uma pessoa: os numeros valem "
        "para esta tarefa e nada alem dela."
    )
    aba_config, aba_execucoes, aba_dashboard = st.tabs(
        ["Configurar e rodar", "Execucoes", "Dashboard"]
    )
    with aba_config:
        tela_de_configuracao()
    with aba_execucoes:
        tela_de_execucoes()
    with aba_dashboard:
        tela_de_dashboard()


principal()
