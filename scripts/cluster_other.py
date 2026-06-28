"""Cluster the OTHER bucket in a cards JSONL to surface new taxonomy candidates.

When the OTHER rate grows (new agent versions, new task types), it signals that
the taxonomy has gaps. This script embeds the OTHER cards' root_cause + evidence
text using TF-IDF and clusters them, then prints the top terms per cluster as
candidate new category descriptions.

Usage
-----
    python scripts/cluster_other.py data/traces/real_cards.jsonl
    python scripts/cluster_other.py data/traces/real_cards.jsonl --clusters 4

Requirements
------------
scikit-learn is an optional dependency — install with:
    pip install scikit-learn

If scikit-learn is not installed the script falls back to keyword-frequency
analysis (useful as a quick scan without any install).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def _load_other_cards(path: Path) -> list[dict]:
    cards = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            card = json.loads(line)
        except json.JSONDecodeError:
            continue
        if card.get("primary_category") == "OTHER":
            cards.append(card)
    return cards


def _card_text(card: dict) -> str:
    parts = [card.get("root_cause", "")]
    for ev in card.get("evidence", []):
        parts.append(ev.get("excerpt", ""))
        parts.append(ev.get("why", ""))
    return " ".join(p for p in parts if p)


def _keyword_fallback(cards: list[dict], n_top: int = 20) -> None:
    """Simple keyword frequency analysis — no sklearn required."""
    stopwords = {
        "the", "a", "an", "is", "was", "of", "in", "to", "and", "or", "at",
        "by", "for", "with", "on", "not", "no", "it", "this", "that", "be",
        "are", "were", "as", "has", "have", "had", "did", "do", "does",
        "step", "agent", "run", "code", "file", "error", "exit", "none",
        "true", "false", "from", "but", "its", "which", "their", "there",
    }
    all_tokens: list[str] = []
    for card in cards:
        text = _card_text(card).lower()
        tokens = re.findall(r"\b[a-z][a-z_]{2,}\b", text)
        all_tokens.extend(t for t in tokens if t not in stopwords)

    freq = Counter(all_tokens)
    print(f"\nTop {n_top} terms in {len(cards)} OTHER card(s):")
    for term, count in freq.most_common(n_top):
        bar = "#" * min(count, 40)
        print(f"  {term:<30s} {count:>4d}  {bar}")
    print(
        "\nLook for recurring themes above. If a cluster of terms appears in "
        "3+ runs, consider adding it as a new taxonomy category."
    )


def _sklearn_cluster(cards: list[dict], n_clusters: int) -> None:
    try:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        print("scikit-learn not installed. Falling back to keyword frequency analysis.")
        _keyword_fallback(cards)
        return

    texts = [_card_text(c) for c in cards]
    vec = TfidfVectorizer(
        max_features=300,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
    )
    X = vec.fit_transform(texts)

    n_clusters = min(n_clusters, len(cards))
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    feature_names = vec.get_feature_names_out()
    order_centroids = km.cluster_centers_.argsort()[:, ::-1]

    print(f"\nClustered {len(cards)} OTHER card(s) into {n_clusters} group(s):\n")
    for k in range(n_clusters):
        member_ids = [cards[i].get("task_id", cards[i].get("run_id", f"card-{i}")) for i, lbl in enumerate(labels) if lbl == k]
        top_terms = [feature_names[j] for j in order_centroids[k, :10]]
        print(f"Cluster {k + 1} ({len(member_ids)} card(s))")
        print(f"  Top terms: {', '.join(top_terms)}")
        print(f"  Members:   {', '.join(member_ids[:5])}" + (" ..." if len(member_ids) > 5 else ""))
        print()

    print(
        "Review each cluster's top terms. If a cluster has a coherent failure "
        "pattern shared across multiple repos, it is a taxonomy-gap candidate.\n"
        "To promote: add a new FailureCategory in src/agent_triage/taxonomy/categories.py "
        "and bump TAXONOMY_VERSION."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards_file", help="Path to a cards JSONL file (e.g. data/traces/real_cards.jsonl)")
    parser.add_argument("--clusters", "-k", type=int, default=3, help="Number of clusters (default: 3)")
    parser.add_argument("--keyword-only", action="store_true", help="Use keyword frequency only (no sklearn)")
    args = parser.parse_args()

    path = Path(args.cards_file)
    if not path.exists():
        sys.exit(f"File not found: {path}")

    cards = _load_other_cards(path)
    if not cards:
        print(f"No OTHER cards found in {path}. OTHER rate is 0% — nothing to cluster.")
        return

    print(f"Found {len(cards)} OTHER card(s) in {path}")

    if args.keyword_only or len(cards) < args.clusters:
        _keyword_fallback(cards)
    else:
        _sklearn_cluster(cards, args.clusters)


if __name__ == "__main__":
    main()
