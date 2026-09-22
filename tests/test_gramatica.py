"""Invariants of the synthetic corpus.

Every check here started as a real defect in a generated text: a report that named the
accused two sentences before saying it did not know who it was, a label of one person
affected on a text about the whole team, a sentence that told the reader the case was not
urgent. A case whose text contradicts its label measures nothing, so these stay as tests.
"""

from __future__ import annotations

import random
import re
from typing import Any

import pytest
import yaml

from lab.casos import carregar_caso

CASO = carregar_caso("canal-de-denuncia")
gerar = CASO.modulo("gerar")
tipos = CASO.modulo("tipos")

SEM_RUIDO_DE_CAIXA = ("formal", "coloquial", "prolixo", "giria_regional")


@pytest.fixture(scope="module")
def dataset() -> dict[str, Any]:
    """The dataset as committed, which is what any published number is computed from."""
    carregado: dict[str, Any] = yaml.safe_load(CASO.dataset.read_text(encoding="utf-8"))
    return carregado


@pytest.fixture(scope="module")
def casos(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    lista: list[dict[str, Any]] = dataset["casos"]
    return lista


def test_o_arquivo_versionado_e_reproduzivel_a_partir_da_semente(dataset: dict[str, Any]) -> None:
    """Regenerating with the recorded seed must reproduce the committed file exactly.

    This is the whole claim of the corpus. If it fails, either the grammar changed without
    the dataset being regenerated, or something non-deterministic crept into the generator.
    """
    gerado = gerar.montar_documento(gerar.Gerador(dataset["semente"]).gerar(), dataset["semente"])
    assert gerado == dataset


def test_classes_balanceadas_por_construcao(dataset: dict[str, Any]) -> None:
    por_urgencia = dataset["distribuicao"]["por_urgencia"]
    niveis = [por_urgencia[str(n)] for n in range(4)]
    assert len(set(niveis)) == 1, f"niveis desbalanceados: {por_urgencia}"
    assert por_urgencia["indeterminado"] > 0


def test_todo_caso_aparece_nos_oito_registros(casos: list[dict[str, Any]]) -> None:
    registros_por_combinacao: dict[str, set[str]] = {}
    for caso in casos:
        combinacao = caso["id"].rsplit("-", 1)[0]
        registros_por_combinacao.setdefault(combinacao, set()).add(caso["registro"])
    assert {len(r) for r in registros_por_combinacao.values()} == {8}


def test_o_texto_nunca_opina_sobre_o_rotulo(casos: list[dict[str, Any]]) -> None:
    """A sentence that says "this is not urgent" hands the model the answer."""
    proibidos = ("nao e urgente", "e urgente", "caso grave", "prioridade maxima")
    vazados = [c["id"] for c in casos if any(p in c["texto"].lower() for p in proibidos)]
    assert not vazados, vazados[:5]


def test_alcance_do_texto_nao_contradiz_o_rotulo(casos: list[dict[str, Any]]) -> None:
    grupo = ("a equipe do", "o time inteiro", "os erros do time", "todo o grupo")
    vazados = [
        c["id"]
        for c in casos
        if c["rotulo"]["sinais"]["afetados"] == "uma_pessoa"
        and any(g in c["texto"].lower() for g in grupo)
    ]
    assert not vazados, vazados[:5]


def test_acusado_nao_e_nomeado_quando_a_hierarquia_e_indeterminada(
    casos: list[dict[str, Any]],
) -> None:
    """The reports that cannot say who did it must not name them."""
    for caso in casos:
        if caso["rotulo"]["sinais"]["hierarquia_do_acusado"] != "indeterminado":
            continue
        # {pessoa2} is the person affected and may be named; {pessoa} is the accused and
        # is replaced. The generator draws the accused as a male name, so its presence is
        # what would be the contradiction.
        assert "{pessoa}" not in caso["texto"]


def test_frases_comecam_em_maiuscula_nos_registros_sem_ruido_de_caixa(
    casos: list[dict[str, Any]],
) -> None:
    quebrados = [
        c["id"]
        for c in casos
        if c["registro"] in SEM_RUIDO_DE_CAIXA and re.search(r"\. [a-z]", c["texto"])
    ]
    assert not quebrados, quebrados[:5]


def test_canarios_de_pii_estao_mesmo_no_texto(casos: list[dict[str, Any]]) -> None:
    """The anonymizer's recall test reads these values, so they have to be findable."""
    com_pii = [c for c in casos if c["pii"].get("estruturada")]
    assert com_pii, "nenhum canario plantado"
    for caso in com_pii:
        for item in caso["pii"]["estruturada"]:
            assert item["valor"] in caso["texto"], caso["id"]


def test_casos_ambiguos_abstem_em_vez_de_rotular(casos: list[dict[str, Any]]) -> None:
    ambiguos = [c for c in casos if c["rotulo"]["sinais_ambiguos"]]
    assert ambiguos
    assert all(c["rotulo"]["urgencia"] is None for c in ambiguos)


def test_urgencia_registrada_bate_com_a_regra_de_composicao(casos: list[dict[str, Any]]) -> None:
    """The label in the file is the composition function's output, not an opinion."""
    for caso in casos:
        if caso["rotulo"]["sinais_ambiguos"]:
            continue
        sinais = tipos.Sinais(**caso["rotulo"]["sinais"])
        composicao = tipos.compor_urgencia(sinais)
        esperado = None if composicao.urgencia is None else int(composicao.urgencia)
        assert caso["rotulo"]["urgencia"] == esperado, caso["id"]
        assert caso["rotulo"]["regra"] == composicao.regra


def test_registro_nunca_descarta_uma_frase_de_sinal() -> None:
    """Only the opening and the closing may be dropped; a signal sentence never is."""
    gerador = gerar.Gerador(1)
    fragmentos = [
        gerar.Fragmento("abertura", "Prezados, segue relato."),
        gerar.Fragmento("nucleo", "Aconteceu algo no setor."),
        gerar.Fragmento("sinal", "Isso continua acontecendo ate hoje."),
        gerar.Fragmento("sinal", "Tenho print das mensagens."),
        gerar.Fragmento("fechamento", "Fico a disposicao."),
    ]
    for registro in gerador.registros:
        texto = gerador._aplicar_registro(fragmentos, registro, random.Random(7))
        for frase in ("continua acontecendo", "print das mensagens"):
            palavras = frase.split()
            # Typos and stopword removal rewrite the sentence, so the check is that its
            # content words survive, not the sentence verbatim.
            assert any(p[:5].lower() in texto.lower() for p in palavras), (registro["id"], texto)


def test_cargo_do_acusado_some_quando_a_hierarquia_e_indeterminada(
    casos: list[dict[str, Any]],
) -> None:
    """A report that cannot say who did it must not announce their job either.

    Found by running Laya against the corpus, not by a test: the text said "alguem,
    diretor do juridico" while the label said the hierarchy was indeterminate. The model
    answered "alta_lideranca" and was right; the label was wrong.
    """
    cargos = ("diretor", "gerente", "supervisor", "coordenador", "encarregado")
    vazados = [
        c["id"]
        for c in casos
        if c["rotulo"]["sinais"]["hierarquia_do_acusado"] == "indeterminado"
        and any(f"alguem, {cargo}" in c["texto"].lower() for cargo in cargos)
    ]
    assert not vazados, vazados[:5]
