"""Whole-session retrieval that preserves chronological source text.

The caller supplies access-filtered sources. Dates and roles are data, never
instructions or approval. This module accepts no evaluation labels.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import math
import re

from .workspace import _terms


def _tokens(text: str) -> list[str]:
    """Unstemmed words and Japanese bigrams; no task-specific vocabulary."""
    lowered=text.casefold()
    result=re.findall(r"[a-z0-9][a-z0-9_-]{2,}",lowered)
    for word in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+",lowered):
        result.extend(word[i:i+2] for i in range(len(word)-1))
    return result


def _bm25(request: str, texts: list[str]) -> list[float]:
    """Standard BM25, k1=1.2, b=0.75, with smoothed positive IDF."""
    counters=[Counter(_tokens(text)) for text in texts]
    sizes=[sum(c.values()) for c in counters]
    average=sum(sizes)/len(sizes) if sizes else 1
    average=average or 1
    df=Counter(term for counter in counters for term in counter)
    query=set(_tokens(request))
    scores=[]
    for count,size in zip(counters,sizes):
        score=0.0
        for term in query:
            freq=count[term]
            if not freq:continue
            idf=math.log(1+(len(texts)-df[term]+0.5)/(df[term]+0.5))
            score+=idf*freq*2.2/(freq+1.2*(0.25+0.75*size/average))
        scores.append(score)
    return scores


def retrieve(request: str, sources: list[dict], *, method: str = "overlap",
             limit: int = 6) -> list[dict]:
    if not isinstance(request, str) or not request.strip():
        raise ValueError("request must be nonempty")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if method == "full":
        return deepcopy(sources)
    if method not in {"overlap", "bm25", "turn_bm25"}:
        raise ValueError("unknown retrieval method")
    query = _terms(request)
    texts=["\n".join(turn["content"] for turn in s["turns"]) for s in sources]
    if method == "bm25":
        scores = _bm25(request, texts)
    elif method == "turn_bm25":
        # Index each turn independently, but return the complete original
        # session. IDF is computed over the same global turn corpus; session
        # score is the strongest matching turn, avoiding long-session dilution.
        turn_texts = [turn["content"] for source in sources for turn in source["turns"]]
        turn_scores = _bm25(request, turn_texts)
        scores = []
        offset = 0
        for source in sources:
            count = len(source["turns"])
            scores.append(max(turn_scores[offset:offset + count], default=0.0))
            offset += count
    else:
        scores = [len(query & _terms(text)) for text in texts]
    ranked = []
    for i, score in enumerate(scores):
        if score:
            ranked.append((score, i))
    selected = {i for _, i in sorted(ranked, key=lambda p: (-p[0], p[1]))[:limit]}
    # Keep supplied order, explicit dates, complete turns and stable IDs.
    return [deepcopy(s) for i, s in enumerate(sources) if i in selected]
