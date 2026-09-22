"""The holdout's own checks.

The holdout exists to catch one thing: a grammar that leaked its labels into the corpus it
trained on. Every failure mode here is one that would destroy that ability quietly - a
label typed instead of composed, a case pasted from the grammar, a template mistaken for
written work. None of them show up as a bad metric; they show up as a good one.

The texts below are deliberately short and flat. They are test fixtures, not holdout
material: the real thing is written by hand by the people whose judgement the labels are.
"""

from __future__ import annotations

from typing import Any

import pytest

from lab import holdout
from lab.casos import carregar_caso

CASO = carregar_caso("canal-de-denuncia")
tipos = CASO.modulo("tipos")

SINAIS_GRAVES = {
    "risco_fisico_iminente": False,
    "em_andamento": True,
    "retaliacao": False,
    "hierarquia_do_acusado": "gestor_direto",
    "afetados": "um_time",
    "tem_evidencia": True,
}


def _documento(*casos: dict[str, Any]) -> dict[str, Any]:
    base = holdout.modelo_de_arquivo("canal-de-denuncia", ["Victor"])
    base["casos"] = list(casos)
    return base


def test_o_rotulo_e_composto_e_nao_digitado() -> None:
    caso = holdout.novo_caso(
        texto="O chefe vem trocando a escala da equipe sem aviso desde o mes passado.",
        sinais=SINAIS_GRAVES,
        cenario="assedio_moral",
        autor="Victor",
    )
    assert caso["rotulo"]["urgencia"] == 2
    assert caso["rotulo"]["regra"] == "R4"
    assert caso["registro"] == "humano"
    assert holdout.validar(_documento(caso)).valido


def test_urgencia_que_nao_segue_dos_sinais_e_erro() -> None:
    """Someone editing the YAML by hand and typing a level is the failure this catches."""
    caso = holdout.novo_caso(
        texto="O chefe vem trocando a escala da equipe sem aviso desde o mes passado.",
        sinais=SINAIS_GRAVES,
        cenario="assedio_moral",
        autor="Victor",
    )
    caso["rotulo"]["urgencia"] = 3

    relatorio = holdout.validar(_documento(caso))
    assert not relatorio.valido
    assert "compor_urgencia" in str(relatorio.erros[0])


def test_texto_copiado_da_gramatica_e_erro() -> None:
    """A holdout built from the grammar cannot detect the grammar leaking its labels."""
    import yaml

    gramatica = yaml.safe_load(
        (CASO.diretorio / "gramatica" / "sinais.yaml").read_text(encoding="utf-8")
    )
    emprestado = gramatica["em_andamento"]["sim"]["direto"][0]

    caso = holdout.novo_caso(
        texto=f"Aconteceu de novo ontem. {emprestado}",
        sinais=SINAIS_GRAVES,
        cenario="assedio_moral",
        autor="Victor",
    )
    relatorio = holdout.validar(_documento(caso))
    assert not relatorio.valido
    assert "gramatica" in str(relatorio.erros[0])


def test_modelo_vazio_nao_passa_por_holdout_escrito() -> None:
    documento = holdout.modelo_de_arquivo("canal-de-denuncia")
    documento["casos"] = [
        {
            "id": "esqueleto",
            "texto": holdout.PLACEHOLDER,
            "autor": "Victor",
            "rotulo": {"sinais": SINAIS_GRAVES, "urgencia": 2, "sinais_ambiguos": []},
        }
    ]
    relatorio = holdout.validar(documento)
    assert not relatorio.valido
    assert "nao foi escrito" in str(relatorio.erros[0])


def test_texto_repetido_e_erro() -> None:
    texto = "A gerente mudou minha escala logo depois que procurei o canal."
    primeiro = holdout.novo_caso(texto, SINAIS_GRAVES, "retaliacao", "Victor")
    segundo = holdout.novo_caso(
        texto + " ", SINAIS_GRAVES, "retaliacao", "Henrique", identificador="outro"
    )
    relatorio = holdout.validar(_documento(primeiro, segundo))
    assert not relatorio.valido
    assert "repetido" in str(relatorio.erros[0])


def test_pii_no_texto_vira_aviso() -> None:
    caso = holdout.novo_caso(
        texto="A gerente mudou minha escala. Meu contato e fulano@exemplo.com.br.",
        sinais=SINAIS_GRAVES,
        cenario="retaliacao",
        autor="Victor",
    )
    relatorio = holdout.validar(_documento(caso))
    assert relatorio.valido, "PII e aviso, nao erro: o holdout e inventado, mas o autor decide"
    assert any("email" in str(p) for p in relatorio.avisos)


def test_sinal_ambiguo_manda_o_caso_para_abstencao() -> None:
    caso = holdout.novo_caso(
        # O primeiro texto que escrevi aqui caiu na checagem de vazamento: eu tinha
        # parafraseado uma frase da gramatica sem perceber. E o comportamento certo.
        texto="Uma colega comentou algo no corredor e ficou por isso; nao apurei se segue.",
        sinais=SINAIS_GRAVES,
        cenario="assedio_moral",
        autor="Henrique",
        sinais_ambiguos=["em_andamento"],
    )
    assert caso["rotulo"]["urgencia"] is None
    assert caso["rotulo"]["regra"] == "R-ambiguo"
    assert holdout.validar(_documento(caso)).valido


def test_avisa_quando_falta_caso_e_quando_um_nivel_esta_vazio() -> None:
    caso = holdout.novo_caso(
        texto="O chefe vem trocando a escala da equipe sem aviso desde o mes passado.",
        sinais=SINAIS_GRAVES,
        cenario="assedio_moral",
        autor="Victor",
    )
    avisos = " ".join(str(p) for p in holdout.validar(_documento(caso)).avisos)
    assert "1 de 60" in avisos
    assert "nivel 3" in avisos


def test_execucao_recusa_holdout_invalido(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run on a broken holdout would spend money to produce a number nobody can use."""
    import yaml

    from lab.execucao import carregar_dataset

    ruim = holdout.modelo_de_arquivo("canal-de-denuncia", ["Victor"])
    caso = holdout.novo_caso(
        "A gerente mudou minha escala logo depois que procurei o canal.",
        SINAIS_GRAVES,
        "retaliacao",
        "Victor",
    )
    caso["rotulo"]["urgencia"] = 0
    ruim["casos"] = [caso]

    destino = tmp_path / "holdout.yaml"
    destino.write_text(yaml.safe_dump(ruim, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(type(CASO), "holdout", property(lambda self: destino))

    with pytest.raises(ValueError, match="nao passou na validacao"):
        carregar_dataset("canal-de-denuncia", "holdout")
