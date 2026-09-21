"""Deterministic PII removal pipeline. No LLM is involved at any layer.

Layer 1 matches formats and validates check digits; layer 2 handles proper names
with a gazetteer, optional statistical NER and a stable pseudonym. Canaries
measure recall in CI. See ``docs/anonimizacao.md``.
"""

__version__ = "0.1.0"
