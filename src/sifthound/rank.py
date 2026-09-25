"""Lexical relevance scoring (BM25) used to pick the best chunks of a page and to score results."""

import math
import re
from collections import Counter

_TOKEN = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or that the this to "
    "was were what when where which who why will with".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q_terms = set(tokenize(query))
    tokenized = [tokenize(d) for d in docs]
    if not q_terms or not tokenized:
        return [0.0] * len(docs)
    n = len(tokenized)
    avgdl = sum(len(t) for t in tokenized) / n or 1.0
    df = Counter(term for toks in tokenized for term in set(toks) if term in q_terms)
    scores = []
    for toks in tokenized:
        tf = Counter(toks)
        dl = len(toks)
        s = 0.0
        for term in q_terms:
            if not tf[term]:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores


def chunk(text: str, max_chars: int = 500) -> list[str]:
    """Split on paragraph boundaries, packing paragraphs into chunks of up to max_chars."""
    chunks: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        while len(para) > max_chars:  # hard-wrap oversized paragraphs at a word boundary
            cut = para.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def best_chunks(query: str, text: str, n: int) -> tuple[list[str], float]:
    """Return the n most relevant chunks (in document order) and the top chunk's BM25 score."""
    chunks = chunk(text)
    if not chunks:
        return [], 0.0
    scores = bm25_scores(query, chunks)
    top = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:n]
    return [chunks[i] for i in sorted(top)], max(scores)


def combine_scores(relevance: list[float], weight: float = 0.6) -> list[float]:
    """Blend normalized lexical relevance with the search engine's own rank order.

    The upstream engine's ordering already carries strong signals (links, freshness), so
    position acts as a prior; BM25 re-sorts within it. Output is in [0, 1].
    """
    top = max(relevance, default=0.0) or 1.0
    return [
        round(weight * (r / top) + (1 - weight) / (1 + 0.2 * i), 4) for i, r in enumerate(relevance)
    ]
