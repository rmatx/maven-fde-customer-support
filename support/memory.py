"""Stage 8 (R-1..R-6): Mem0 recall before the agent, save after the Masker. The agent has no memory tool."""
import os
os.environ.setdefault("MEM0_TELEMETRY", "False")
from mem0 import AsyncMemory

TOPK, MINSCORE, MAXCHARS = 5, 0.50, 500   # T-MEM-TOPK, T-MEM-MINSCORE (0.25 -> 0.50: Ollama nomic-embed-text scores unrelated memories up to 0.55, true ones 0.53-0.81), T-MEM-MAXCHARS
HEADER = "Relevant memories about this customer (from Mem0):"
_client = None


CONFIG = {   # self-hosted Mem0 OSS: Qdrant server for vectors, Ollama for embeddings. No LLM runs (infer=False); the entry only satisfies the config.
    "vector_store": {"provider": "qdrant", "config": {"host": os.getenv("QDRANT_HOST", "127.0.0.1"), "port": int(os.getenv("QDRANT_PORT", "6335")),
                                                      "collection_name": "support_memories", "embedding_model_dims": 768}},
    "embedder": {"provider": "ollama", "config": {"model": "nomic-embed-text", "embedding_dims": 768,
                                                  "ollama_base_url": os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")}},
    "llm": {"provider": "ollama", "config": {"model": "nomic-embed-text", "ollama_base_url": os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")}},
}


def client() -> AsyncMemory:
    global _client
    if _client is None:
        _client = AsyncMemory.from_config(CONFIG)
    return _client


async def recall(user_email: str, message: str) -> list[dict]:
    """Every candidate with its score and whether it will be inserted (R-2, R-5)."""
    res = await client().search(message, filters={"user_id": user_email}, top_k=TOPK, threshold=0.0)   # self-hosted: no platform reranker; MINSCORE below does the filtering
    out = []
    for m in res.get("results", []):
        text, score = m.get("memory", ""), float(m.get("score") or 0)
        reason = "too long" if len(text) > MAXCHARS else "below cutoff" if score < MINSCORE else None
        out.append({"memory": text, "score": round(score, 3), "inserted": reason is None, "reason": reason})
    return out


def with_memories(message: str, candidates: list[dict]) -> str:
    kept = [c["memory"] for c in candidates if c["inserted"]]
    if not kept:
        return message
    return HEADER + "\n" + "\n".join(f"- {k}" for k in kept) + "\n\nCustomer message:\n" + message


async def save(user_email: str, message: str):
    """Save ONLY what the user said (R-4)."""
    # infer=False stores the message verbatim. With inference on, Mem0 decides with an LLM what to keep: it dropped 4 of 10
    # planted facts in one eval run, and its merge step is the source of the R-7 runaway memory. Verbatim is deterministic.
    return await client().add([{"role": "user", "content": message}], user_id=user_email, infer=False)


async def clear(user_email: str):
    return await client().delete_all(user_id=user_email)
