"""
MPNet + Cosine Similarity ONLY
"""

import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import MPNet Embedding
from utils.embedding import get_embeddings

# Import database config
from models.database import ScreeningConfig


def calculate_mpnet_cosine_similarity(text1: str, text2: str) -> float:
    """
    Hitung similarity menggunakan MPNet + Cosine Similarity
    """
    try:
        max_length = 2000

        text1 = text1[:max_length] if text1 else ""
        text2 = text2[:max_length] if text2 else ""

        emb1 = get_embeddings(text1)
        emb2 = get_embeddings(text2)

        similarity = float(np.dot(emb1, emb2))

        return max(0.0, min(1.0, similarity))

    except Exception as e:
        logger.error(f"MPNet similarity error: {e}")
        return 0.0


def perform_screening(job_text: str, cv_text: str):
    """
    Screening menggunakan MPNet + Cosine Similarity
    dengan threshold dinamis dari dashboard admin
    """

    # Hitung similarity
    score = calculate_mpnet_cosine_similarity(job_text, cv_text)

    # Default threshold
    recommended_threshold = 0.6

    try:
        # Ambil threshold dari database
        config = ScreeningConfig.query.first()

        if config:
            recommended_threshold = config.recommended_threshold

    except Exception as e:
        logger.error(f"Threshold config error: {e}")

    # Decision rules
    if score >= recommended_threshold:
        decision = 'recommended'
    else:
        decision = 'not_recommended'

    logger.info(f"""
    📊 SCREENING RESULT:
        MPNet Score: {score:.3f}
        Recommended Threshold: {recommended_threshold}
        Decision: {decision}
    """)

    return {
        'score': score,
        'decision': decision
    }