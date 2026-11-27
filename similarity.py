from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"\w+", re.UNICODE)


def content_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for row, char_a in enumerate(a, start=1):
        current = [row]
        for column, char_b in enumerate(b, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (char_a != char_b),
            ))
        previous = current
    return 1.0 - previous[-1] / max(len(a), len(b))


def context_similarity(a: str, b: str) -> float:
    tokens_a = Counter(_TOKEN.findall(a.casefold()))
    tokens_b = Counter(_TOKEN.findall(b.casefold()))
    if not tokens_a or not tokens_b:
        return 1.0 if not tokens_a and not tokens_b else 0.0

    dot = sum(count * tokens_b.get(token, 0) for token, count in tokens_a.items())
    norm_a = math.sqrt(sum(count * count for count in tokens_a.values()))
    norm_b = math.sqrt(sum(count * count for count in tokens_b.values()))
    return min(1.0, max(0.0, dot / (norm_a * norm_b)))


def combined_similarity(
    content_a: str,
    content_b: str,
    context_a: str,
    context_b: str,
) -> float:
    return 0.6 * content_similarity(content_a, content_b) + 0.4 * context_similarity(
        context_a, context_b
    )
