# utils/embedding.py
from __future__ import annotations
import os
import numpy as np
from functools import lru_cache
import logging
import warnings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== MOCK SYSTEM UNTUK HANDLE TORCH ERROR =====
TORCH_AVAILABLE = False
SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
    logger.info(f"✅ Torch loaded: {torch.__version__}")
except ImportError as e:
    logger.warning(f"⚠️ Torch not found: {e}")
    warnings.warn("Torch not available, using mock embeddings")
except OSError as e:
    logger.warning(f"⚠️ Torch DLL error: {e}")
    warnings.warn(f"Torch loading failed: {e}. Using mock embeddings for development.")

# Coba import sentence_transformers
try:
    if TORCH_AVAILABLE:
        from sentence_transformers import SentenceTransformer
        SENTENCE_TRANSFORMERS_AVAILABLE = True
        logger.info("✅ SentenceTransformer loaded successfully")
    else:
        # Force raise error untuk trigger mock
        raise ImportError("Torch not available")
except (ImportError, OSError) as e:
    logger.warning(f"⚠️ SentenceTransformer import failed: {e}")
    
    # ===== CREATE MOCK SentenceTransformer =====
    class MockSentenceTransformer:
        def __init__(self, model_name: str = "sentence-transformers/all-mpnet-base-v2", device: str = None):
            self.model_name = model_name
            self.device = device or "cpu"
            self.dimension = 384  # MiniLM-L6-v2 dimension
            logger.info(f"🔄 Initialized MockSentenceTransformer: {model_name}, dim={self.dimension}")
            
        def encode(self, texts, batch_size: int = 32, 
                   convert_to_numpy: bool = True, 
                   normalize_embeddings: bool = True,
                   show_progress_bar: bool = False, **kwargs):
            
            import numpy as np
            import hashlib
            
            # Handle single text or list
            is_single = isinstance(texts, str)
            if is_single:
                texts = [texts]
            
            embeddings = []
            for i, text in enumerate(texts):
                if not isinstance(text, str):
                    text = "" if text is None else str(text)
                
                # Create deterministic pseudo-random embedding based on text hash
                text_hash = hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()
                seed = int(text_hash[:8], 16) % (2**32 - 1)
                
                # Use numpy random with seed
                rng = np.random.RandomState(seed)
                vec = rng.randn(self.dimension).astype(np.float32)
                
                # Normalize if requested (should always be True for cosine similarity)
                if normalize_embeddings:
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                
                embeddings.append(vec)
            
            result = np.array(embeddings) if convert_to_numpy else embeddings
            
            # Return single vector for single text
            if is_single:
                return result[0] if convert_to_numpy else embeddings[0]
            return result
        
        def __repr__(self):
            return f"MockSentenceTransformer(model_name='{self.model_name}', dim={self.dimension})"
    
    # Replace SentenceTransformer with mock
    SentenceTransformer = MockSentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.info("🔄 Using MockSentenceTransformer for embeddings")
# ===== END MOCK SYSTEM =====

# Konfigurasi
_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
_DEVICE = os.getenv("EMBEDDING_DEVICE", None)  # "cuda" | "cpu" | None (auto)
_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

_model = None

def _get_model():
    print("🔥 MODEL YANG DIPAKAI:", _MODEL_NAME)
    global _model
    if _model is None:
        if SENTENCE_TRANSFORMERS_AVAILABLE and TORCH_AVAILABLE:
            # Use real SentenceTransformer
            _model = SentenceTransformer(_MODEL_NAME, device=_DEVICE)
            logger.info(f"✅ Loaded REAL SentenceTransformer: {_MODEL_NAME}")
        else:
            # Use mock
            _model = SentenceTransformer(_MODEL_NAME, device="cpu")
            logger.info(f"🔄 Using MOCK model: {_MODEL_NAME}")
    return _model

def get_embeddings(text: str) -> np.ndarray:
    """
    Embedding single text → np.ndarray shape (D,), float32, normalized.
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    
    model = _get_model()

    vec = model.encode(
        text,
        batch_size=1,
        convert_to_numpy=True,
        normalize_embeddings=True,  # langsung unit vector → cosine = dot
        show_progress_bar=False,
    )
    # Pastikan 1D float32
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    return vec

def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """
    Embedding list of text → np.ndarray shape (N, D), float32, normalized.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)  # 384 untuk MiniLM; aman walau tak terpakai
    
    texts = [t if isinstance(t, str) else ("" if t is None else str(t)) for t in texts]
    model = _get_model()
    
    mat = model.encode(
        texts,
        batch_size=_BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(mat, dtype=np.float32)

# (Opsional) cache ringan untuk single text
@lru_cache(maxsize=4096)
def get_embeddings_cached(text: str) -> tuple:
    """
    Versi cacheable untuk teks tunggal (return tuple agar hashable).
    Cocok untuk katalog job yang sering dipakai berulang.
    """
    v = get_embeddings(text)
    return tuple(v.tolist())

# ===== TEST FUNCTION (JALANKAN MANUAL) =====
def _test_embeddings():
    """Test fungsi embeddings - JANGAN DIJALANKAN OTOMATIS"""
    print("🧪 Testing embeddings...")
    
    # Test single text
    text1 = "software engineer with python experience"
    vec1 = get_embeddings(text1)
    print(f"✅ Single text embedding shape: {vec1.shape}, dtype: {vec1.dtype}")
    print(f"   Norm: {np.linalg.norm(vec1):.6f} (should be ~1.0)")
    
    # Test batch
    texts = ["machine learning", "data science", "web development"]
    mat = get_embeddings_batch(texts)
    print(f"✅ Batch embeddings shape: {mat.shape}")
    
    # Test similarity (should be deterministic)
    vec2 = get_embeddings(text1)
    similarity = np.dot(vec1, vec2)
    print(f"✅ Self-similarity: {similarity:.6f} (should be ~1.0)")
    
    # Test different texts
    vec3 = get_embeddings("different text")
    similarity_diff = np.dot(vec1, vec3)
    print(f"✅ Different text similarity: {similarity_diff:.6f}")
    
    return True

# HAPUS ATAU COMMENT INI UNTUK HINDARI CIRCULAR IMPORT
# if __name__ == "__main__":
#     _test_embeddings()