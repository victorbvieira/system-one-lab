"""Generate the synthetic dataset for the whistleblowing case. No LLM is involved.

A seeded combinatorial grammar: scenario x flag combination x linguistic register, with
slots filled by Faker's ``pt_BR`` locale. The label comes from the flags, never from the
text, so it is auditable and it is nobody's opinion.

Run it with ``uv run python casos/canal-de-denuncia/gerar.py``. The same seed and the same
grammar produce the same ``dataset.yaml``, byte for byte; the file records the seed and a
hash of the grammar so a reader can tell whether a change to one explains a change to the
numbers. See ``docs/metodologia.md`` for the reasoning behind each choice here.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from faker import Faker

from lab.casos import carregar_caso

CASO = carregar_caso("canal-de-denuncia")
tipos = CASO.tipos

GRAMATICA = CASO.diretorio / "gramatica"
SEMENTE_PADRAO = 20260921
VERSAO_DO_FORMATO = 1

# The dates in the reports are drawn from a window anchored here, not from "the last three
# years" counted from today. A window that moves with the wall clock makes the corpus
# irreproducible: the same seed gives a different file tomorrow, which is exactly what
# `test_o_arquivo_versionado_e_reproduzivel_a_partir_da_semente` caught one day after it
# was written. The anchor is recorded in the dataset so the file says what "recent" meant.
DATA_DE_REFERENCIA = date(2026, 9, 21)
JANELA_DE_DATAS_EM_DIAS = 3 * 365

# Per scenario: how many flag combinations to draw for each urgency level, plus the two
# abstention slots. Drawing per level instead of sampling the space is what keeps the
# classes balanced by construction rather than by luck - and the distribution report
# exists to prove it stayed that way.
COMBINACOES_POR_NIVEL = 3
COMBINACOES_INDETERMINADAS = 2

_BOOLEANOS = ("risco_fisico_iminente", "em_andamento", "retaliacao", "tem_evidencia")
_LIGACAO = re.compile(r"^(Ademais|Cumpre informar que|Por oportuno|Ai|E tambem|Fora que)\s+")


def _carregar(nome: str) -> Any:
    return yaml.safe_load((GRAMATICA / nome).read_text(encoding="utf-8"))


def hash_da_gramatica() -> str:
    """A hash over every grammar file, so a dataset can be tied to what produced it."""
    digest = hashlib.sha256()
    for caminho in sorted(GRAMATICA.glob("*.yaml")):
        digest.update(caminho.name.encode())
        digest.update(caminho.read_bytes())
    return digest.hexdigest()[:16]


@dataclass
class Fragmento:
    """One sentence and what it is, so the register transforms know what may be dropped."""

    tipo: str
    """``abertura``, ``nucleo``, ``sinal``, ``distrator``, ``pii`` or ``fechamento``."""

    texto: str


@dataclass
class CasoGerado:
    """A generated case, with everything needed to audit its label."""

    id: str
    texto: str
    cenario: str
    registro: str
    sinais: dict[str, Any]
    urgencia: int | None
    regra: str
    motivo: str
    sinais_ambiguos: list[str] = field(default_factory=list)
    ruido: dict[str, Any] = field(default_factory=dict)
    pii: dict[str, Any] = field(default_factory=dict)


class Gerador:
    """The grammar, its seed, and the draw that turns them into cases."""

    def __init__(self, semente: int = SEMENTE_PADRAO) -> None:
        self.semente = semente
        self.cenarios = _carregar("cenarios.yaml")
        self.sinais = _carregar("sinais.yaml")
        self.registros = _carregar("registros.yaml")
        self.ruido = _carregar("ruido.yaml")
        self.slots = _carregar("slots.yaml")
        self.faker = Faker("pt_BR")

    # -- the space of labels -------------------------------------------------------

    def _espaco(self) -> list[dict[str, Any]]:
        """Every flag combination, each with the level it composes to."""
        combinacoes: list[dict[str, Any]] = []
        for rf, ea, ret, ev in itertools.product([False, True], repeat=4):
            for hierarquia in tipos.Hierarquia:
                for afetados in tipos.Afetados:
                    sinais = tipos.Sinais(
                        risco_fisico_iminente=rf,
                        em_andamento=ea,
                        retaliacao=ret,
                        hierarquia_do_acusado=hierarquia,
                        afetados=afetados,
                        tem_evidencia=ev,
                    )
                    composicao = tipos.compor_urgencia(sinais)
                    combinacoes.append({"sinais": sinais, "composicao": composicao})
        return combinacoes

    def _sortear_combinacoes(self, rng: random.Random) -> list[dict[str, Any]]:
        """Draw a balanced set of combinations for one scenario."""
        espaco = self._espaco()
        por_nivel: dict[int | None, list[dict[str, Any]]] = {}
        for item in espaco:
            por_nivel.setdefault(item["composicao"].urgencia, []).append(item)

        escolhidas: list[dict[str, Any]] = []
        for nivel in tipos.Urgencia:
            candidatos = por_nivel.get(nivel, [])
            escolhidas.extend(rng.sample(candidatos, min(COMBINACOES_POR_NIVEL, len(candidatos))))
        # One abstention case from an indeterminate enum, one from an ambiguous boolean:
        # the two ways a real report leaves a signal unanswerable.
        indeterminados = por_nivel.get(None, [])
        escolhidas.extend(rng.sample(indeterminados, min(1, len(indeterminados))))
        determinados = [item for item in espaco if item["composicao"].urgencia is not None]
        for item in rng.sample(determinados, COMBINACOES_INDETERMINADAS - 1):
            escolhidas.append({**item, "ambiguo": rng.choice(_BOOLEANOS)})
        return escolhidas

    # -- text ----------------------------------------------------------------------

    def _valores_de_slot(self, rng: random.Random) -> dict[str, str]:
        return {
            # The shared signal phrasings speak of {pessoa} as "ele" and {pessoa2} as
            # "ela", so the names have to agree or the text reads as broken Portuguese.
            # Gender is fixed here, not varied: it is not a variable of this study, and
            # docs/metodologia.md records that as a limitation of the corpus.
            "pessoa": self.faker.name_male(),
            "pessoa2": self.faker.name_female(),
            "cargo": rng.choice(self.slots["cargos"]),
            "setor": rng.choice(self.slots["setores"]),
            "local": rng.choice(self.slots["locais"]),
            "sistema": rng.choice(self.slots["sistemas"]),
            "data": self.faker.date_between_dates(
                DATA_DE_REFERENCIA - timedelta(days=JANELA_DE_DATAS_EM_DIAS),
                DATA_DE_REFERENCIA,
            ).strftime("%d/%m/%Y"),
            "valor": _reais(self.faker.pydecimal(left_digits=4, right_digits=2, positive=True)),
        }

    def _frase_do_sinal(
        self, nome: str, valor: Any, rng: random.Random, eufemismo: bool, ambiguo: bool
    ) -> tuple[str | None, str]:
        """Pick a phrasing for one signal, and say which kind it was."""
        bloco = self.sinais[nome]
        if ambiguo:
            return rng.choice(bloco["ambiguo"]), "ambiguo"
        if nome in _BOOLEANOS:
            ramo = bloco["sim"] if valor else bloco["nao"]
            if valor:
                estilo = "eufemismo" if eufemismo and ramo.get("eufemismo") else "direto"
            else:
                estilo = rng.choice(["neutro", "negacao"])
            return rng.choice(ramo[estilo]), estilo
        ramo = bloco[str(valor)]
        estilo = "eufemismo" if eufemismo and ramo.get("eufemismo") else "direto"
        return rng.choice(ramo[estilo]), estilo

    def _montar(
        self, cenario: dict[str, Any], combinacao: dict[str, Any], rng: random.Random
    ) -> tuple[list[Fragmento], dict[str, Any], dict[str, Any], list[str]]:
        sinais = combinacao["sinais"]
        urgencia = combinacao["composicao"].urgencia
        ambiguo = combinacao.get("ambiguo")

        # Euphemism is the point of the exercise, so it is drawn most often exactly where
        # it hurts most: a level 3 written without a single alarming word.
        chance = {3: 0.55, 2: 0.4}.get(int(urgencia) if urgencia is not None else -1, 0.25)
        eufemismo = rng.random() < chance

        fragmentos = [
            Fragmento("abertura", rng.choice(cenario["aberturas"])),
            Fragmento("nucleo", rng.choice(_no_alcance(cenario["nucleos"], sinais.afetados))),
        ]
        estilos: dict[str, str] = {}
        frases_de_sinal: list[Fragmento] = []
        for nome in (*_BOOLEANOS, "hierarquia_do_acusado", "afetados"):
            valor = getattr(sinais, nome)
            eh_ambiguo = nome == ambiguo
            # A false boolean that is simply not mentioned still reads as false, which is
            # how most reports are written. An enum left out would read as indeterminate,
            # so those are always said.
            if not eh_ambiguo and nome in _BOOLEANOS and not valor and rng.random() < 0.4:
                estilos[nome] = "omitido"
                continue
            frase, estilo = self._frase_do_sinal(nome, valor, rng, eufemismo, eh_ambiguo)
            estilos[nome] = estilo
            if frase:
                frases_de_sinal.append(Fragmento("sinal", frase))
        rng.shuffle(frases_de_sinal)
        fragmentos.extend(frases_de_sinal)

        ruido: dict[str, Any] = {
            "eufemismo": [n for n, e in estilos.items() if e == "eufemismo"],
            "negacao": [n for n, e in estilos.items() if e == "negacao"],
            "omitidos": [n for n, e in estilos.items() if e == "omitido"],
            "distrator": False,
        }
        # A lexical distractor only belongs where it can do damage: an alarming word in a
        # case that is not urgent. On a level 3 it would prove nothing.
        if urgencia is not None and urgencia <= 1 and rng.random() < 0.35:
            fragmentos.append(Fragmento("distrator", rng.choice(self.ruido["distratores"])))
            ruido["distrator"] = True

        pii: dict[str, Any] = {"estruturada": []}
        if rng.random() < 0.18:
            canario = rng.choice(self.ruido["canarios"])
            valor_pii = self._valor_de_pii(canario["tipo"])
            fragmentos.append(Fragmento("pii", canario["frase"].replace("{valor_pii}", valor_pii)))
            pii["estruturada"].append({"tipo": canario["tipo"], "valor": valor_pii})

        fragmentos.append(Fragmento("fechamento", rng.choice(self.sinais["fechamentos"])))
        return fragmentos, ruido, pii, ([ambiguo] if ambiguo else [])

    def _valor_de_pii(self, tipo: str) -> str:
        gerador = {
            "cpf": self.faker.cpf,
            "cnpj": self.faker.cnpj,
            "telefone": self.faker.phone_number,
            "email": self.faker.email,
            "cep": self.faker.postcode,
            "placa": self.faker.license_plate,
        }[tipo]
        return str(gerador())

    # -- register ------------------------------------------------------------------

    def _aplicar_registro(
        self, fragmentos: list[Fragmento], registro: dict[str, Any], rng: random.Random
    ) -> str:
        """Rewrite the assembled sentences in one register, never touching the label.

        Only the opening and the closing may be dropped. Every sentence that carries a
        signal survives every register, which is what makes the same label defensible
        across all eight.
        """
        mantidos = [
            f
            for f in fragmentos
            if f.texto
            and not (registro.get("sem_abertura") and f.tipo == "abertura")
            and not (registro.get("sem_fechamento") and f.tipo == "fechamento")
        ]
        frases = [f.texto for f in mantidos]

        if ligacoes := registro.get("ligacoes"):
            # Drawn without replacement: the same connector three times in one report
            # reads as a template, which is what the registers exist to hide.
            disponiveis = rng.sample(ligacoes, len(ligacoes))
            frases = [
                _ligar(frase, disponiveis.pop())
                if i and disponiveis and rng.random() < 0.3
                else frase
                for i, frase in enumerate(frases)
            ]
        if enchimentos := registro.get("enchimentos"):
            for enchimento in rng.sample(enchimentos, k=min(2, len(enchimentos))):
                frases.insert(rng.randrange(1, len(frases) + 1), enchimento)

        texto = " ".join(frases)

        for de, para in (registro.get("substituicoes") or {}).items():
            texto = re.sub(rf"\b{re.escape(de)}\b", para, texto, flags=re.IGNORECASE)
        if registro.get("remover_conectivos"):
            texto = ". ".join(_LIGACAO.sub("", frase) for frase in texto.split(". "))
            texto = texto.replace(", mas ", ". ").replace(", e ", ". ")
        if registro.get("encurtar"):
            texto = re.sub(r"\b(que|de|do|da|no|na|para|com|uma|um)\b ", "", texto)

        # Character-level noise is applied around the planted PII, never to it. A canary
        # exists to measure the anonymizer's recall, and a CPF with a swapped digit is no
        # longer a CPF: the check digit fails, the deterministic layer is right not to
        # match it, and the CI gate would be measuring the typist instead. PII that
        # arrives corrupted is a real problem, and an explicitly out-of-scope one -
        # see docs/metodologia.md.
        protegidos = [f.texto for f in mantidos if f.tipo == "pii"]
        texto = self._ruido_de_digitacao(texto, registro, rng, protegidos)

        return ((registro.get("prefixo") or "") + texto).strip()

    def _ruido_de_digitacao(
        self, texto: str, registro: dict[str, Any], rng: random.Random, protegidos: list[str]
    ) -> str:
        """Apply typos and shouting to everything but the stretches listed in ``protegidos``."""
        if not (registro.get("taxa_de_erro") or registro.get("taxa_de_caixa_alta")):
            return texto

        pedacos: list[tuple[str, bool]] = [(texto, False)]
        for protegido in protegidos:
            novos: list[tuple[str, bool]] = []
            for pedaco, intocavel in pedacos:
                if intocavel or protegido not in pedaco:
                    novos.append((pedaco, intocavel))
                    continue
                antes, _, depois = pedaco.partition(protegido)
                novos.extend([(antes, False), (protegido, True), (depois, False)])
            pedacos = novos

        saida: list[str] = []
        for pedaco, intocavel in pedacos:
            if intocavel or not pedaco:
                saida.append(pedaco)
                continue
            if taxa := registro.get("taxa_de_erro"):
                pedaco = self._errar(pedaco, taxa, rng)
            if taxa := registro.get("taxa_de_caixa_alta"):
                pedaco = " ".join(
                    p.upper() if rng.random() < taxa else p for p in pedaco.split(" ")
                )
            saida.append(pedaco)
        return "".join(saida)

    @staticmethod
    def _errar(texto: str, taxa: float, rng: random.Random) -> str:
        """Typos of the kind a hurried person makes: a swap, a doubled or a missing letter."""
        letras = list(texto)
        for i in range(1, len(letras) - 1):
            if letras[i].isalpha() and rng.random() < taxa:
                escolha = rng.random()
                if escolha < 0.4:
                    letras[i], letras[i - 1] = letras[i - 1], letras[i]
                elif escolha < 0.7:
                    letras[i] = ""
                else:
                    letras[i] = letras[i] * 2
        return "".join(letras)

    # -- the draw ------------------------------------------------------------------

    def gerar(self) -> list[CasoGerado]:
        """Every case, in a deterministic order."""
        casos: list[CasoGerado] = []
        for cenario in self.cenarios:
            # One stream per scenario, seeded from the run seed and the scenario name, so
            # adding a scenario does not reshuffle the cases of the ones before it.
            semente_do_cenario = self.semente + int(
                hashlib.sha256(cenario["id"].encode()).hexdigest()[:8], 16
            )
            rng = random.Random(semente_do_cenario)
            self.faker.seed_instance(semente_do_cenario)
            combinacoes = self._sortear_combinacoes(rng)
            for indice, combinacao in enumerate(combinacoes):
                fragmentos, ruido, pii, ambiguos = self._montar(cenario, combinacao, rng)
                slots = self._valores_de_slot(rng)
                pii["nomes"] = sorted({slots["pessoa"], slots["pessoa2"]})
                anonimo = (
                    combinacao["sinais"].hierarquia_do_acusado is tipos.Hierarquia.INDETERMINADO
                )
                for registro in self.registros:
                    bruto = [
                        Fragmento(f.tipo, _anonimizar(f.texto, anonimo).format_map(_Slots(slots)))
                        for f in fragmentos
                    ]
                    texto = self._aplicar_registro(bruto, registro, rng)
                    composicao = combinacao["composicao"]
                    urgencia = None if ambiguos else composicao.urgencia
                    casos.append(
                        CasoGerado(
                            id=f"{cenario['id']}-{indice:02d}-{registro['id']}",
                            texto=texto,
                            cenario=cenario["id"],
                            registro=registro["id"],
                            sinais={
                                nome: (valor.value if hasattr(valor, "value") else valor)
                                for nome, valor in combinacao["sinais"].model_dump().items()
                            },
                            urgencia=None if urgencia is None else int(urgencia),
                            regra="R-ambiguo" if ambiguos else composicao.regra,
                            motivo=(
                                "Um sinal booleano ficou ambiguo no texto; o caso abstem."
                                if ambiguos
                                else composicao.motivo
                            ),
                            sinais_ambiguos=ambiguos,
                            ruido=ruido,
                            pii={k: v for k, v in pii.items() if v},
                        )
                    )
        return casos


def _ligar(frase: str, ligacao: str) -> str:
    """Prefix a sentence with a connector, lowercasing it only when there is one."""
    if not ligacao or not frase:
        return frase
    return ligacao + frase[0].lower() + frase[1:]


def _reais(valor: object) -> str:
    """Format a decimal the way Brazil writes money: thousands with a dot, cents with a comma."""
    return "R$ " + f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _no_alcance(nucleos: list[Any], afetados: Any) -> list[str]:
    """The cores whose own wording does not contradict the labelled reach.

    A core that says "the whole team works without protection" cannot carry a label of one
    person affected. Those cores declare an ``alcance`` in the grammar and are only drawn
    when the label agrees; the neutral ones are always available, including for a case
    whose reach is indeterminate - there the text must not give the answer away.
    """
    escolhidos = []
    for nucleo in nucleos:
        if isinstance(nucleo, str):
            escolhidos.append(nucleo)
        elif nucleo["alcance"] == str(afetados):
            escolhidos.append(nucleo["texto"])
    return escolhidos


# ", {cargo} do {setor}" and ", {cargo}," are appositions that name the accused's role.
# They have to go along with the name: a model found the contradiction they left behind
# before any test did - a report saying "alguem, diretor do juridico" announces the
# hierarchy the label had recorded as indeterminate, and the model's "alta_lideranca" was
# right against a label that was wrong.
_APOSICAO_DE_CARGO = re.compile(r",\s*\{cargo\}(\s+d[oa]\s+\{setor\})?")


def _anonimizar(frase: str, anonimo: bool) -> str:
    """Strip what identifies the accused when the report says it does not know who it was.

    Naming someone - or their job - two sentences before saying "I do not know who it was"
    is a contradiction in the text, and a case whose text contradicts its label measures
    nothing.
    """
    if not anonimo:
        return frase
    trocada = _APOSICAO_DE_CARGO.sub("", frase.replace("{pessoa}", "alguem"))
    return trocada[0].upper() + trocada[1:] if trocada else trocada


class _Slots(dict[str, str]):
    """Leave an unknown slot in place instead of raising, so a typo is visible in the text."""

    def __missing__(self, chave: str) -> str:  # pragma: no cover - defensive
        return "{" + chave + "}"


def distribuicao(casos: list[CasoGerado]) -> dict[str, Any]:
    """The class distribution, which is the first thing to check in a generated dataset."""
    def contar(chave: Any) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for caso in casos:
            valor = chave(caso)
            contagem[str(valor)] = contagem.get(str(valor), 0) + 1
        return dict(sorted(contagem.items()))

    return {
        "total": len(casos),
        "por_urgencia": contar(lambda c: "indeterminado" if c.urgencia is None else c.urgencia),
        "por_cenario": contar(lambda c: c.cenario),
        "por_registro": contar(lambda c: c.registro),
        "por_regra": contar(lambda c: c.regra),
        "com_eufemismo": sum(1 for c in casos if c.ruido.get("eufemismo")),
        "com_negacao": sum(1 for c in casos if c.ruido.get("negacao")),
        "com_distrator": sum(1 for c in casos if c.ruido.get("distrator")),
        "com_pii_estruturada": sum(1 for c in casos if c.pii.get("estruturada")),
        "tamanho_medio_em_caracteres": round(
            sum(len(c.texto) for c in casos) / max(len(casos), 1)
        ),
    }


def montar_documento(casos: list[CasoGerado], semente: int) -> dict[str, Any]:
    """The dataset file: provenance first, then the cases."""
    return {
        "versao": VERSAO_DO_FORMATO,
        "caso": "canal-de-denuncia",
        "origem": (
            "Gramatica combinatoria deterministica. Nenhum LLM escreveu qualquer texto "
            "deste arquivo. Ver docs/metodologia.md."
        ),
        "semente": semente,
        "gramatica_hash": hash_da_gramatica(),
        "data_de_referencia": DATA_DE_REFERENCIA.isoformat(),
        "idioma": "pt-BR",
        "distribuicao": distribuicao(casos),
        "casos": [
            {
                "id": caso.id,
                "texto": caso.texto,
                "cenario": caso.cenario,
                "registro": caso.registro,
                "rotulo": {
                    "sinais": caso.sinais,
                    "urgencia": caso.urgencia,
                    "regra": caso.regra,
                    "motivo": caso.motivo,
                    "sinais_ambiguos": caso.sinais_ambiguos,
                },
                "ruido": caso.ruido,
                "pii": caso.pii,
            }
            for caso in casos
        ],
    }


def escrever(documento: dict[str, Any], destino: Path) -> None:
    """Write the dataset as readable YAML: this file is meant to be opened and argued with."""
    destino.write_text(
        yaml.safe_dump(documento, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def main() -> None:
    analise = argparse.ArgumentParser(description=__doc__)
    analise.add_argument("--semente", type=int, default=SEMENTE_PADRAO)
    analise.add_argument("--destino", type=Path, default=CASO.dataset)
    argumentos = analise.parse_args()

    gerador = Gerador(argumentos.semente)
    casos = gerador.gerar()
    documento = montar_documento(casos, argumentos.semente)
    escrever(documento, argumentos.destino)

    resumo = documento["distribuicao"]
    print(f"{resumo['total']} casos em {argumentos.destino}")
    print(f"  semente {argumentos.semente}, gramatica {documento['gramatica_hash']}")
    for chave in ("por_urgencia", "por_registro"):
        print(f"  {chave}: {resumo[chave]}")
    for chave in ("com_eufemismo", "com_negacao", "com_distrator", "com_pii_estruturada"):
        print(f"  {chave}: {resumo[chave]}")


if __name__ == "__main__":
    main()
