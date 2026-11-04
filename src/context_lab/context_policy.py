"""Choose evidence coverage explicitly before retrieval.

An exhaustive request cannot be answered reliably by assuming that top-k
search found every item. Auto routing is a conservative convenience, not a
semantic completeness proof; callers can always request all visible sources.
"""
import re


_EXHAUSTIVE = re.compile(
    r"\b(?:how many|how much|total|altogether|every|all of|list all|ever)\b"
    r"|合計|総(?:数|額|量)|全部|全件|すべて|全て|何(?:件|回|個|人|枚|冊|台)|一度でも|網羅",
    re.IGNORECASE,
)


def coverage_policy(request: str, coverage: str = "auto") -> dict:
    if not isinstance(request,str) or not request.strip():
        raise ValueError("request must be nonempty")
    if coverage not in {"auto","all","ranked"}:
        raise ValueError("coverage must be auto, all, or ranked")
    exhaustive=coverage=="all" or coverage=="auto" and bool(_EXHAUSTIVE.search(request))
    return {"requested":coverage,"selected":"all" if exhaustive else "ranked",
            "reason":"explicit_all" if coverage=="all" else
                "exhaustive_language" if exhaustive else "ranked_lookup",
            "completeness_note":"All means all supplied access-visible source snapshots, not all external knowledge. Auto is a heuristic; select all explicitly for completeness-critical work."}
