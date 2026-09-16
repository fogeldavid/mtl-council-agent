"""Multilingual embeddings, run locally at ingestion time.

Source documents are French-only; user questions arrive in French or English.
multilingual-e5 puts both languages in one shared space, so an English
question retrieves French passages without translating anything at ingestion
time. Running it locally means corpus growth costs compute, not API spend --
the paid model budget is reserved for answering.

e5 models are trained with asymmetric prefixes and degrade noticeably without
them: stored text must be prefixed "passage: ", user questions "query: ".
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "intfloat/multilingual-e5-base"
EMBEDDING_DIM = 768


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_passages(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(
        [f"passage: {t}" for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    vector = _model().encode(
        f"query: {text}",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vector.tolist()
