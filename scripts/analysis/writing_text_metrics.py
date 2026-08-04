"""Japanese free-text indicators for the Writing task 60 analysis.

The indicators are deliberately dictionary-based and interpretable.  They are
proxies for how an answer is written; they are not automatic scores of whether
an interpretation is correct or relevant to the watched videos.
"""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

try:
    from janome.tokenizer import Tokenizer
except ImportError as error:  # pragma: no cover - exercised only in a broken env
    raise ImportError(
        "本文指標にはJanomeが必要です。pip install -r requirements-analysis.txt "
        "を実行してください。"
    ) from error


TEXT_QUESTION_MEASURES = (
    "content_word_count",
    "lexical_diversity_mattr",
    "content_word_ratio",
    "causal_marker_rate",
    "reflection_marker_rate",
    "specificity_marker_rate",
    "sentence_length_tokens",
)

TEXT_OVERALL_METRICS = (
    "Mean_content_word_count",
    "Mean_lexical_diversity_mattr",
    "Mean_content_word_ratio",
    "Mean_causal_marker_rate",
    "Mean_reflection_marker_rate",
    "Mean_specificity_marker_rate",
    "Mean_sentence_length_tokens",
)

TEXT_METRIC_LABELS = {
    "Mean_content_word_count": "Content words per answer",
    "Mean_lexical_diversity_mattr": "Lexical diversity (content-word MATTR)",
    "Mean_content_word_ratio": "Content-word ratio",
    "Mean_causal_marker_rate": "Causal/elaborative markers per 100 tokens",
    "Mean_reflection_marker_rate": "Reflective markers per 100 tokens",
    "Mean_specificity_marker_rate": "Specificity markers per 100 tokens",
    "Mean_sentence_length_tokens": "Tokens per sentence",
}

# Multi-character expressions are counted before single-token analysis.  The
# short, fixed lists keep the score auditable and avoid a model-dependent NLP
# judgement.
CAUSAL_EXPRESSIONS = (
    "なぜなら", "そのため", "だから", "したがって", "ゆえに", "からこそ",
    "ことによって",
)
CAUSAL_LEMMAS = {"結果", "理由", "原因", "影響", "きっかけ"}
REFLECTION_LEMMAS = {
    "思う", "感じる", "考える", "気づく", "気付く", "理解", "捉える",
    "見方", "価値観", "自分", "私", "心", "感情", "印象", "疑問", "問い",
}

_SENTENCE_SPLIT = re.compile(r"[。！？!?]+")
_QUOTED_TERM = re.compile(r"[「『][^」』]{1,30}[」』]")
_TOKENIZER = Tokenizer()


@lru_cache(maxsize=4096)
def _token_rows(text: str) -> tuple[tuple[str, str, str], ...]:
    rows = []
    for token in _TOKENIZER.tokenize(text):
        parts = token.part_of_speech.split(",")
        coarse = parts[0]
        detail = parts[1] if len(parts) > 1 else ""
        if coarse in {"記号", "フィラー", "その他"}:
            continue
        base = token.base_form if token.base_form != "*" else token.surface
        rows.append((token.surface, base, f"{coarse},{detail}"))
    return tuple(rows)


def _mattr(items: list[str], window: int = 20) -> float:
    if not items:
        return np.nan
    if len(items) <= window:
        return len(set(items)) / len(items)
    values = [
        len(set(items[start : start + window])) / window
        for start in range(len(items) - window + 1)
    ]
    return float(np.mean(values))


def calculate_text_metrics(value: object) -> dict[str, float]:
    """Return seven interpretable indicators for one Japanese answer."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return {measure: np.nan for measure in TEXT_QUESTION_MEASURES}
    text = str(value).strip()
    if not text:
        return {measure: np.nan for measure in TEXT_QUESTION_MEASURES}

    rows = _token_rows(text)
    token_count = len(rows)
    if token_count == 0:
        return {measure: np.nan for measure in TEXT_QUESTION_MEASURES}

    content_rows = [
        row for row in rows
        if row[2].split(",", 1)[0] in {"名詞", "動詞", "形容詞", "副詞"}
    ]
    content_lemmas = [row[1] for row in content_rows]
    all_lemmas = [row[1] for row in rows]
    proper_or_number = sum(
        row[2] in {"名詞,固有名詞", "名詞,数"} for row in content_rows
    )
    specificity_count = proper_or_number + len(_QUOTED_TERM.findall(text))
    sentence_count = max(1, len([part for part in _SENTENCE_SPLIT.split(text) if part.strip()]))
    scale = 100.0 / token_count

    return {
        "content_word_count": float(len(content_rows)),
        "lexical_diversity_mattr": _mattr(content_lemmas),
        "content_word_ratio": len(content_rows) / token_count,
        "causal_marker_rate": (
            sum(text.count(marker) for marker in CAUSAL_EXPRESSIONS)
            + sum(lemma in CAUSAL_LEMMAS for lemma in all_lemmas)
        ) * scale,
        "reflection_marker_rate": sum(
            lemma in REFLECTION_LEMMAS for lemma in all_lemmas
        ) * scale,
        "specificity_marker_rate": specificity_count * scale,
        "sentence_length_tokens": token_count / sentence_count,
    }
