"""本地向量化：bge-small-zh-v1.5 via fastembed（onnxruntime 推理，不依赖 torch）。

模型缓存在项目目录 models/ 下，不占 C 盘。
首次运行会自动下载约 100MB，走 hf-mirror 镜像。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 必须在 import fastembed 之前设置
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(MODEL_DIR))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# hf-mirror 不支持 Xet 传输协议，必须禁用，否则大文件下载报 401
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DIM = 512
# fastembed 实际使用的是 Qdrant 转换版，缓存目录名与之对应
HF_CACHE = MODEL_DIR / "hf"

_model = None


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(HF_CACHE))
    return _model


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    """把对话内容向量化后入库。"""
    model = get_model()
    fn = getattr(model, "passage_embed", None) or model.embed
    return [np.asarray(v, dtype=np.float32) for v in fn(texts)]


def embed_query(text: str) -> np.ndarray:
    """把检索语句向量化。bge 系列对 query/passage 用不同前缀，分开处理效果更好。"""
    model = get_model()
    fn = getattr(model, "query_embed", None) or model.embed
    return np.asarray(next(iter(fn([text]))), dtype=np.float32)


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def top_k(query: np.ndarray, matrix: np.ndarray, k: int, min_score: float = 0.35) -> list[tuple[int, float]]:
    """余弦相似度暴力检索。向量已归一化，点积即余弦。"""
    if matrix.size == 0:
        return []
    q = query / (np.linalg.norm(query) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    sims = (matrix / norms) @ q
    idx = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in idx if sims[i] >= min_score]
