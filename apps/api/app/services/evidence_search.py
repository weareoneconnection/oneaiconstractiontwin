"""Relevance search over project evidence.

Ask Twin previously attached "the first five evidence rows of the project" to every
answer, which made the evidence-first policy decorative: the same evidence came back
regardless of the question. This module implements an actual retrieval step (BM25
over the evidence corpus) so that a claim is only ever supported by evidence that
mentions what the question is about.

BM25 is deliberate: it is transparent, needs no model server, is deterministic, and
its scores can be shown to a customer. It can be swapped for a vector index later
without changing the calling contract.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Evidence

# Bounded so a large project cannot pull an unbounded corpus into memory.
CANDIDATE_LIMIT = 2000

STOPWORDS = frozenset(
    """a an and are as at be been by did do does for from had has have how i in is it its of on or
    that the this to was were what when where which who why will with why's you your our""".split()
)

TOKEN_RE = re.compile(r"[a-z0-9]+")

# A small, explicit construction vocabulary. Question wording and site-record wording
# rarely coincide ("why is it delayed" vs "installation suspended"), and without this
# the retriever misses records that plainly answer the question. The map is lexical
# and auditable on purpose: it adds terms, it never invents facts.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "delay": ("delayed", "late", "slip", "slipped", "slippage", "suspended", "stopped", "behind", "overrun"),
    "delayed": ("delay", "late", "slip", "slipped", "suspended", "behind"),
    "late": ("delay", "delayed", "slip", "behind", "overrun"),
    "cause": ("reason", "because", "due", "root"),
    "crane": ("lifting", "hoist", "equipment", "plant"),
    "equipment": ("crane", "plant", "machine", "hoist"),
    "delivery": ("delivered", "shipment", "material", "supply", "dlv"),
    "delivered": ("delivery", "shipment", "material", "supply"),
    "material": ("delivery", "delivered", "supply", "shipment"),
    "weather": ("rain", "storm", "wind", "typhoon", "snow"),
    "quality": ("ncr", "defect", "inspection", "rework", "nonconformance"),
    "safety": ("incident", "accident", "hazard", "injury"),
    "install": ("installation", "installed", "erect", "erection", "fix"),
    "installed": ("install", "installation", "erection"),
    "progress": ("complete", "completion", "percent", "status"),
    "steel": ("beam", "column", "member", "plate", "girder"),
    "beam": ("steel", "member", "girder"),
    "labour": ("labor", "crew", "manpower", "resource", "workforce"),
    "labor": ("labour", "crew", "manpower", "resource", "workforce"),
}


def expand(terms: list[str]) -> list[str]:
    """Add known lexical variants, preserving order and removing duplicates."""
    expanded: list[str] = []
    for term in terms:
        for candidate in (term, *SYNONYMS.get(term, ())):
            if candidate not in expanded:
                expanded.append(candidate)
    return expanded


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class ScoredEvidence:
    evidence: Evidence
    score: float
    matched_terms: list[str]


def _document_text(row: Evidence) -> str:
    fragment = " ".join(str(value) for value in (row.fragment or {}).values())
    return f"{row.content} {row.source_type} {row.source_id} {fragment}"


def search_evidence(
    db: Session,
    tenant_id: str,
    organization_id: str,
    project_id: str,
    question: str,
    limit: int = 5,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[ScoredEvidence]:
    """Return evidence ranked by BM25 relevance to `question`. Empty when nothing matches."""
    asked = tokenize(question)
    if not asked:
        return []
    terms = expand(asked)
    # Expanded terms are worth less than the words the user actually typed.
    weights = {term: (1.0 if term in asked else 0.45) for term in terms}

    rows = list(
        db.scalars(
            select(Evidence)
            .where(
                Evidence.project_id == project_id,
                Evidence.tenant_id == tenant_id,
                Evidence.organization_id == organization_id,
            )
            .order_by(Evidence.created_at.desc())
            .limit(CANDIDATE_LIMIT)
        ).all()
    )
    if not rows:
        return []

    documents = [tokenize(_document_text(row)) for row in rows]
    lengths = [len(doc) or 1 for doc in documents]
    average_length = sum(lengths) / len(lengths)
    document_frequency: dict[str, int] = {}
    for doc in documents:
        for term in set(doc):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    results: list[ScoredEvidence] = []
    for row, doc, length in zip(rows, documents, lengths):
        counts: dict[str, int] = {}
        for token in doc:
            counts[token] = counts.get(token, 0) + 1
        score = 0.0
        matched: list[str] = []
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            matched.append(term)
            idf = math.log(1 + (len(rows) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            score += weights[term] * idf * (frequency * (k1 + 1)) / (frequency + k1 * (1 - b + b * length / average_length))
        if score > 0:
            # Source confidence modulates ranking: a low-confidence record should not
            # outrank a high-confidence one on lexical overlap alone.
            results.append(ScoredEvidence(row, round(score * (0.5 + 0.5 * float(row.confidence or 1.0)), 4), matched))

    results.sort(key=lambda item: (-item.score, item.evidence.created_at))
    return [item for item in results if _is_a_real_match(item, document_frequency, len(rows))][:limit]


#: A term carried by most of the corpus ("zone", "site", "works") says nothing about
#: which record answers a question.
COMMON_TERM_RATIO = 0.6

#: BM25 scores are unbounded, but a hit this weak is noise at any corpus size.
MINIMUM_SCORE = 0.35


def _is_a_real_match(hit: ScoredEvidence, document_frequency: dict[str, int], corpus_size: int) -> bool:
    """Reject hits that only coincide on words common to nearly every record.

    On a small corpus BM25's IDF term is too flat to do this on its own: a question
    about a concrete pour would retrieve three unrelated records because each of them
    happens to say "Zone". Treating that as evidence is worse than finding nothing —
    it turns "I have no record of this" into a confident-looking answer.
    """
    if hit.score < MINIMUM_SCORE:
        return False
    if not hit.matched_terms:
        return False
    distinctive = [
        term for term in hit.matched_terms
        if document_frequency.get(term, 0) / max(1, corpus_size) < COMMON_TERM_RATIO
    ]
    return bool(distinctive)
