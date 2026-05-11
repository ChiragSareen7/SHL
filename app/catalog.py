import json
import logging
import os
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

log = logging.getLogger(__name__)

_catalog: list[dict] = []
_url_set: set[str] = set()
_vectorizer: TfidfVectorizer | None = None
_matrix = None  # sparse TF-IDF matrix


def _catalog_path() -> Path:
    env_path = os.getenv("CATALOG_PATH", "catalog.json")
    p = Path(env_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    return p


def load_catalog() -> list[dict]:
    global _catalog, _url_set
    path = _catalog_path()
    if not path.exists():
        raise FileNotFoundError(f"catalog.json not found at {path}")
    with open(path, encoding="utf-8") as f:
        _catalog = json.load(f)
    _url_set = {item["url"] for item in _catalog}
    log.info(f"Loaded {len(_catalog)} assessments from {path}")
    return _catalog


def build_index() -> None:
    global _vectorizer, _matrix
    if not _catalog:
        raise RuntimeError("Catalog not loaded. Call load_catalog() first.")
    texts = [_item_to_text(item) for item in _catalog]
    _vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    _matrix = _vectorizer.fit_transform(texts)
    log.info(f"TF-IDF index built: {_matrix.shape[0]} docs, {_matrix.shape[1]} terms.")


def _item_to_text(item: dict) -> str:
    parts = [
        item.get("name", ""),
        item.get("description", ""),
        " ".join(item.get("keys", [])),
        item.get("test_type", ""),
    ]
    return " ".join(p for p in parts if p)


def semantic_search(query: str, top_k: int = 15) -> list[dict]:
    """TF-IDF cosine similarity search (replaces sentence-transformer embeddings)."""
    if _vectorizer is None or _matrix is None:
        log.warning("Index not built; falling back to keyword search.")
        return keyword_search(query, top_k)
    q_vec = _vectorizer.transform([query])
    scores = cosine_similarity(q_vec, _matrix).flatten()
    indices = np.argsort(scores)[::-1][:top_k]
    return [_catalog[int(i)] for i in indices if scores[i] > 0]


def keyword_search(query: str, top_k: int = 15) -> list[dict]:
    query_tokens = query.lower().split()
    scored: list[tuple[float, dict]] = []
    for item in _catalog:
        score = 0.0
        name_l = item.get("name", "").lower()
        desc_l = item.get("description", "").lower()
        keys_l = " ".join(item.get("keys", [])).lower()
        for token in query_tokens:
            if len(token) < 3:
                continue
            if token in name_l:
                score += 4.0
            if token in keys_l:
                score += 2.0
            if token in desc_l:
                score += 1.0
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def hybrid_search(query: str, top_k: int = 15) -> list[dict]:
    """Combine TF-IDF + keyword search via Reciprocal Rank Fusion."""
    sem_results = semantic_search(query, top_k=top_k)
    kw_results = keyword_search(query, top_k=top_k)

    k = 60
    rrf_scores: dict[str, float] = {}
    url_to_item: dict[str, dict] = {}

    for rank, item in enumerate(sem_results):
        url = item["url"]
        rrf_scores[url] = rrf_scores.get(url, 0.0) + 1.0 / (k + rank + 1)
        url_to_item[url] = item

    for rank, item in enumerate(kw_results):
        url = item["url"]
        rrf_scores[url] = rrf_scores.get(url, 0.0) + 1.0 / (k + rank + 1)
        url_to_item[url] = item

    sorted_urls = sorted(rrf_scores, key=lambda u: rrf_scores[u], reverse=True)
    return [url_to_item[u] for u in sorted_urls[:top_k]]


def get_all() -> list[dict]:
    return _catalog


def get_url_set() -> set[str]:
    return _url_set


def url_exists(url: str) -> bool:
    return url in _url_set
