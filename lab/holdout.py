"""The hand-written holdout: its schema, its validator, and how a case is added to it.

The synthetic corpus measures whether the approach works. It does not prove that it works
in the world, because a grammar can only test what someone thought to put in it. The
holdout is the correction for that: sixty reports written and labelled by hand, without the
grammar, and the metric that goes in the article is this one.

Nothing here writes a report. By definition it cannot: a holdout produced by the same
process as the training corpus is not a holdout, and a holdout produced by a language model
would carry that model's idea of what a complaint sounds like into the benchmark that
judges language models. What this module does is make the manual work fast and keep it
honest - the label is computed from the signals rather than typed, and the checks below
refuse a file that has quietly drifted back into being generated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from lab.casos import carregar_caso

__all__ = [
    "PLACEHOLDER",
    "Problema",
    "Relatorio",
    "carregar",
    "distribuicao",
    "escrever",
    "modelo_de_arquivo",
    "normalizar",
    "novo_caso",
    "validar",
]

VERSAO_DO_FORMATO = 1
PLACEHOLDER = "<<escreva o relato aqui>>"
TAMANHO_ALVO = 60
MINIMO_POR_NIVEL = 10

# How many words in a row have to match the grammar before a holdout case is treated as
# having been copied from it. Six is long enough that a shared turn of phrase in Portuguese
# does not trip it, and short enough that a pasted sentence cannot hide.
PALAVRAS_PARA_VAZAMENTO = 6

_PADROES_DE_PII = {
    "cpf": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    "telefone": re.compile(r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "cep": re.compile(r"\b\d{5}-?\d{3}\b"),
}


@dataclass
class Problema:
    """Something wrong with the holdout, and how bad it is."""

    gravidade: str
    """``erro`` blocks the file from being used; ``aviso`` is worth knowing before publishing."""

    caso: str | None
    mensagem: str

    def __str__(self) -> str:
        onde = f" [{self.caso}]" if self.caso else ""
        return f"{self.gravidade}{onde}: {self.mensagem}"


@dataclass
class Relatorio:
    """The outcome of validating a holdout file."""

    problemas: list[Problema] = field(default_factory=list)
    distribuicao: dict[str, Any] = field(default_factory=dict)

    @property
    def erros(self) -> list[Problema]:
        return [p for p in self.problemas if p.gravidade == "erro"]

    @property
    def avisos(self) -> list[Problema]:
        return [p for p in self.problemas if p.gravidade == "aviso"]

    @property
    def valido(self) -> bool:
        """Whether the file can be used to produce a number."""
        return not self.erros


def modelo_de_arquivo(caso: str, autores: list[str] | None = None) -> dict[str, Any]:
    """An empty, documented holdout file.

    It carries the schema and no prose. The placeholder in the one skeleton case is
    rejected by the validator on purpose: an unfilled template must never be mistaken for
    a written holdout.
    """
    return {
        "versao": VERSAO_DO_FORMATO,
        "caso": caso,
        "origem": (
            "Escrito e rotulado a mao, sem usar a gramatica. Nenhum LLM escreveu qualquer "
            "texto deste arquivo. E a metrica que vai no artigo."
        ),
        "autores": autores or [],
        "instrucoes": [
            "Escreva o relato como ele chegaria: na voz de quem denuncia, no registro que "
            "essa pessoa usaria, com o tamanho que ela escreveria.",
            "Nao copie frase da gramatica. O validador recusa trecho identico a ela.",
            "Nao use dado real de ninguem: nome, CPF, telefone, e-mail ou endereco.",
            "Marque os seis sinais pelo que o TEXTO afirma, nao pelo que voce imagina. A "
            "urgencia sai deles por compor_urgencia, nunca digitada a mao.",
            "Se o texto nao permite concluir um sinal, use indeterminado ou marque o sinal "
            "como ambiguo: o caso vai para a metrica de abstencao.",
            f"Alvo: {TAMANHO_ALVO} casos, com ao menos {MINIMO_POR_NIVEL} por nivel.",
        ],
        "casos": [],
    }


def novo_caso(
    texto: str,
    sinais: dict[str, Any],
    cenario: str,
    autor: str,
    caso: str = "canal-de-denuncia",
    notas: str = "",
    sinais_ambiguos: list[str] | None = None,
    identificador: str | None = None,
) -> dict[str, Any]:
    """Build one holdout case, computing the label instead of accepting one.

    Args:
        texto: The report, as written by hand.
        sinais: The six signals, as judged by the person who wrote it.
        cenario: Which scenario it belongs to, from the same list the grammar uses.
        autor: Who wrote and labelled it. Recorded because rotulagem de uma pessoa is a
            declared limitation, and knowing which person matters.
        caso: The case directory.
        notas: Anything the author wants the reader to know about the judgement.
        sinais_ambiguos: Signals the text deliberately leaves open.
        identificador: An explicit id; one is derived from the author and the text if absent.

    Returns:
        The case, in the same shape the synthetic dataset uses, so the runner does not need
        to know which corpus it is reading.
    """
    tipos = carregar_caso(caso).modulo("tipos")
    ambiguos = sinais_ambiguos or []
    validados = tipos.Sinais.model_validate(sinais)
    composicao = tipos.compor_urgencia(validados)
    urgencia = None if ambiguos else composicao.urgencia

    return {
        "id": identificador or _identificador(autor, texto),
        "texto": texto.strip(),
        "cenario": cenario,
        "registro": "humano",
        "autor": autor,
        "escrito_em": date.today().isoformat(),
        "notas": notas,
        "rotulo": {
            "sinais": {
                nome: (valor.value if hasattr(valor, "value") else valor)
                for nome, valor in validados.model_dump().items()
            },
            "urgencia": None if urgencia is None else int(urgencia),
            "regra": "R-ambiguo" if ambiguos else composicao.regra,
            "motivo": (
                "Um sinal ficou ambiguo no texto; o caso abstem." if ambiguos else composicao.motivo
            ),
            "sinais_ambiguos": ambiguos,
        },
        "ruido": {},
        "pii": {},
    }


def _identificador(autor: str, texto: str) -> str:
    import hashlib

    inicial = _sem_acento(autor.split()[0].lower()) if autor.strip() else "anon"
    digest = hashlib.sha256(texto.strip().encode()).hexdigest()[:6]
    return f"holdout-{inicial}-{digest}"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def carregar(caso: str = "canal-de-denuncia") -> dict[str, Any]:
    """Read the holdout file, or a fresh template when it does not exist yet."""
    caminho = carregar_caso(caso).holdout
    if not caminho.is_file():
        return modelo_de_arquivo(caso)
    documento: dict[str, Any] = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    documento.setdefault("casos", [])
    return documento


def escrever(documento: dict[str, Any], caso: str = "canal-de-denuncia") -> Path:
    """Write the holdout file, keeping it readable: it is meant to be opened and argued with."""
    caminho = carregar_caso(caso).holdout
    documento["distribuicao"] = distribuicao(documento["casos"])
    caminho.write_text(
        yaml.safe_dump(documento, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return caminho


def normalizar(documento: dict[str, Any]) -> dict[str, Any]:
    """Fill in what the runner expects, so both corpora read the same.

    A holdout case carries an author and notes that the synthetic one does not, and lacks
    the noise bookkeeping that only a generator can produce. Rather than teach the runner
    about two shapes, the missing keys are filled in here.
    """
    documento = dict(documento)
    documento["casos"] = [
        {
            "ruido": {},
            "pii": {},
            "registro": "humano",
            **caso,
        }
        for caso in documento.get("casos", [])
    ]
    return documento


def distribuicao(casos: list[dict[str, Any]]) -> dict[str, Any]:
    """The same distribution report the synthetic dataset carries, so the two compare."""

    def contar(chave: Any) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for caso in casos:
            valor = str(chave(caso))
            contagem[valor] = contagem.get(valor, 0) + 1
        return dict(sorted(contagem.items()))

    if not casos:
        return {"total": 0}
    return {
        "total": len(casos),
        "por_urgencia": contar(
            lambda c: (
                "indeterminado" if c["rotulo"]["urgencia"] is None else c["rotulo"]["urgencia"]
            )
        ),
        "por_cenario": contar(lambda c: c.get("cenario", "?")),
        "por_autor": contar(lambda c: c.get("autor", "?")),
        "tamanho_medio_em_caracteres": round(sum(len(c["texto"]) for c in casos) / len(casos)),
    }


def _frases_da_gramatica(caso: str) -> set[str]:
    """Every n-gram the grammar can emit, for the leak check.

    Read from the grammar files rather than from the generated dataset: the dataset has the
    slots already filled, and a holdout case would have different names in them.
    """
    gramatica = carregar_caso(caso).diretorio / "gramatica"
    textos: list[str] = []

    def colher(no: Any) -> None:
        if isinstance(no, str):
            textos.append(no)
        elif isinstance(no, dict):
            for valor in no.values():
                colher(valor)
        elif isinstance(no, list):
            for valor in no:
                colher(valor)

    for arquivo in sorted(gramatica.glob("*.yaml")):
        colher(yaml.safe_load(arquivo.read_text(encoding="utf-8")))

    ngramas: set[str] = set()
    for texto in textos:
        palavras = _palavras(texto)
        for inicio in range(len(palavras) - PALAVRAS_PARA_VAZAMENTO + 1):
            ngramas.add(" ".join(palavras[inicio : inicio + PALAVRAS_PARA_VAZAMENTO]))
    return ngramas


def _palavras(texto: str) -> list[str]:
    """Words, lowercased and unaccented, with the slot markers dropped."""
    limpo = re.sub(r"\{[a-z_0-9]+\}", " ", texto.lower())
    return re.findall(r"[a-z]+", _sem_acento(limpo))


def validar(documento: dict[str, Any], caso: str = "canal-de-denuncia") -> Relatorio:
    """Check a holdout file, and say what would make a number from it wrong.

    The checks, in order of how badly each one would mislead:

    1. A label that does not follow from the signals, which makes the file disagree with
       the rule everything else is measured against.
    2. Text copied from the grammar, which turns the holdout back into the training corpus
       and hides the one failure it exists to detect.
    3. A template left unfilled, a duplicate, a missing field.
    4. Something shaped like real personal data.
    5. Too few cases, or too few in a level, to say anything about that level.
    """
    tipos = carregar_caso(caso).modulo("tipos")
    problemas: list[Problema] = []
    casos = documento.get("casos") or []

    if documento.get("versao") != VERSAO_DO_FORMATO:
        problemas.append(
            Problema("aviso", None, f"versao do formato e {documento.get('versao')!r}.")
        )
    if not documento.get("autores"):
        problemas.append(Problema("aviso", None, "nenhum autor declarado no cabecalho do arquivo."))

    vistos: dict[str, str] = {}
    ngramas = _frases_da_gramatica(caso) if casos else set()

    for caso_do_holdout in casos:
        identificador = str(caso_do_holdout.get("id", "?"))
        texto = str(caso_do_holdout.get("texto", "")).strip()

        if not texto or PLACEHOLDER in texto:
            problemas.append(Problema("erro", identificador, "o relato nao foi escrito."))
            continue
        if not caso_do_holdout.get("autor"):
            problemas.append(
                Problema("erro", identificador, "sem autor: quem rotulou tem de constar.")
            )

        chave = " ".join(_palavras(texto))
        if chave in vistos:
            problemas.append(Problema("erro", identificador, f"texto repetido de {vistos[chave]}."))
        vistos[chave] = identificador

        rotulo = caso_do_holdout.get("rotulo") or {}
        sinais = rotulo.get("sinais") or {}
        try:
            validados = tipos.Sinais.model_validate(sinais)
        except Exception as erro:  # a mensagem do pydantic diz qual campo, e ela basta
            problemas.append(Problema("erro", identificador, f"sinais invalidos: {erro}"))
            continue

        composicao = tipos.compor_urgencia(validados)
        esperada = None if rotulo.get("sinais_ambiguos") else composicao.urgencia
        esperada_int = None if esperada is None else int(esperada)
        if rotulo.get("urgencia") != esperada_int:
            problemas.append(
                Problema(
                    "erro",
                    identificador,
                    f"urgencia gravada e {rotulo.get('urgencia')!r}, mas os sinais compoem "
                    f"{esperada_int!r} pela regra {composicao.regra}. O rotulo nao e digitado: "
                    f"ele sai de compor_urgencia.",
                )
            )

        palavras = _palavras(texto)
        trechos = {
            " ".join(palavras[i : i + PALAVRAS_PARA_VAZAMENTO])
            for i in range(len(palavras) - PALAVRAS_PARA_VAZAMENTO + 1)
        }
        if copiado := trechos & ngramas:
            problemas.append(
                Problema(
                    "erro",
                    identificador,
                    f"trecho identico a gramatica: {sorted(copiado)[0]!r}. Um holdout "
                    f"copiado da gramatica nao detecta vazamento de rotulo, que e a unica "
                    f"coisa que ele existe para detectar.",
                )
            )

        for nome, padrao in _PADROES_DE_PII.items():
            if padrao.search(texto):
                problemas.append(
                    Problema(
                        "aviso",
                        identificador,
                        f"o texto tem algo com cara de {nome}. O holdout e inventado: nao "
                        f"pode carregar dado de ninguem.",
                    )
                )

    resumo = distribuicao(casos)
    if len(casos) < TAMANHO_ALVO:
        problemas.append(
            Problema(
                "aviso",
                None,
                f"{len(casos)} de {TAMANHO_ALVO} casos escritos.",
            )
        )
    for nivel in range(4):
        quantos = (resumo.get("por_urgencia") or {}).get(str(nivel), 0)
        if casos and quantos < MINIMO_POR_NIVEL:
            problemas.append(
                Problema(
                    "aviso",
                    None,
                    f"nivel {nivel} tem {quantos} casos; abaixo de {MINIMO_POR_NIVEL} nao da "
                    f"para publicar metrica por nivel.",
                )
            )

    return Relatorio(problemas=problemas, distribuicao=resumo)
