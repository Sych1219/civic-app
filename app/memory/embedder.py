import json

import numpy as np
from openai import AsyncOpenAI

_client = AsyncOpenAI()
_MODEL = "text-embedding-3-small"

SIMILARITY_THRESHOLD = 0.75
TOP_K_HINTS = 5


async def embed(text: str) -> list[float]:
    resp = await _client.embeddings.create(input=text, model=_MODEL)
    return resp.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def top_k_hints(
    question_emb: list[float],
    hints: list[dict],
    k: int = TOP_K_HINTS,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[str]:
    scored = []
    for h in hints:
        if not h.get("embeddingJson"):
            continue
        h_emb = json.loads(h["embeddingJson"])
        score = cosine_similarity(question_emb, h_emb)
        if score >= threshold:
            scored.append((score, h["body"]))
    scored.sort(reverse=True)
    return [body for _, body in scored[:k]]
