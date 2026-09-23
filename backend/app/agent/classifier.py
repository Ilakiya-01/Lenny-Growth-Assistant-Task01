"""Intent classification.

Two classifiers live here:

* :class:`HeuristicIntentClassifier` - deterministic signal scoring. It is the
  default, needs no provider, costs nothing and works offline.
* :class:`LLMIntentClassifier` - asks the configured provider for a JSON label
  when LLM-assisted routing is switched on. It returns only a label and a
  confidence; model reasoning is never read from, stored in or shown to anyone.

Both return a :class:`ClassificationResult`, so the router is independent of how
the decision was reached.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.agent.intents import Intent
from app.agent.structured import extract_json_object
from app.errors import AgentClassificationError
from app.llm.base import BaseLLMClient, LLMMessage, sanitize_error_text

logger = logging.getLogger("lenny.agent.classifier")

CLASSIFIER_HEURISTIC = "heuristic"
CLASSIFIER_LLM = "llm"

#: A primary intent needs at least this score; otherwise the request is GENERAL.
MIN_PRIMARY_SCORE = 0.5
#: Other intents at or above this score are reported as secondary intents.
SECONDARY_SCORE = 0.45
MAX_CONFIDENCE = 0.97
LOW_SIGNAL_CONFIDENCE = 0.3

_WORD_COUNT_RE = re.compile(r"\b\d{3,4}[\s-]?words?\b", re.IGNORECASE)
_ESSAY_TERMS_RE = re.compile(
    r"\b(essay|article|blog\s?post|newsletter|ship\s?30|ship30for30|long[- ]form|thought piece)\b",
    re.IGNORECASE,
)
_ARTIFACT_TERMS_RE = re.compile(
    r"\b(artifact|landing\s?page|html|css|render(?:able)?|viewer|web\s?page|webpage|mockup|dashboard)\b",
    re.IGNORECASE,
)
_DOCUMENT_TERMS_RE = re.compile(
    r"\b(markdown|document|docs?|report|one[- ]?pager|spec(?:ification)?|memo|strategy doc|roadmap doc)\b",
    re.IGNORECASE,
)
_CREATION_VERB_RE = re.compile(
    r"\b(create|generate|make|produce|turn\b[\s\S]{0,40}?\binto|convert|build|draft|write|compose)\b",
    re.IGNORECASE,
)
_SOURCE_TERMS_RE = re.compile(
    r"\b(lenny|lenny'?s|podcast|episodes?|guests?|transcripts?|interviews?)\b",
    re.IGNORECASE,
)
_ATTRIBUTION_TERMS_RE = re.compile(
    r"\b(say|said|says|mention(?:ed|s)?|advise[ds]?|advice|recommend(?:ed|s|ation)?|"
    r"talk(?:ed|s)?\s+about|discuss(?:ed|es)?|opinions?|quotes?|according to|takeaways?|lessons?)\b",
    re.IGNORECASE,
)
_TOPIC_TERMS_RE = re.compile(
    r"\b(product[- ]market fit|pmf|product[- ]led growth|growth|retention|churn|onboarding|pricing|"
    r"monetization|acquisition|activation|positioning|product management|product strategy|"
    r"roadmap|discovery|user research|go[- ]to[- ]market|fundraising|hiring|leadership|"
    r"marketplace|saas|startups?|metrics?|north star)\b",
    re.IGNORECASE,
)
_INTERROGATIVE_RE = re.compile(
    r"^\s*(what|which|who|whom|whose|how|why|where|when|did|does|do|is|are|was|were|can|could|"
    r"should|would|tell me|explain|summarize|summarise|list)\b",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"\b(hello|hi|hey|yo|howdy|good (?:morning|afternoon|evening)|how are you|how'?s it going|"
    r"what'?s up|greetings)\b",
    re.IGNORECASE,
)
_COURTESY_RE = re.compile(r"\b(thanks|thank you|cheers|bye|goodbye|see you|that'?s all)\b", re.IGNORECASE)
_META_RE = re.compile(
    r"\b(who are you|what are you|your name|what can you do|what do you do|help me get started|"
    r"what are your capabilities)\b",
    re.IGNORECASE,
)
_QUESTION_FORM_RE = re.compile(r"\?\s*$")

#: Scoring rules per intent: (signal code, pattern, weight). Weights are chosen
#: so a single unambiguous signal clears MIN_PRIMARY_SCORE.
_SIGNAL_RULES: tuple[tuple[Intent, tuple[tuple[str, re.Pattern[str], float], ...]], ...] = (
    (
        Intent.SHIP30FOR30,
        (
            ("ship30:word_count", _WORD_COUNT_RE, 0.6),
            ("ship30:essay_terms", _ESSAY_TERMS_RE, 0.55),
        ),
    ),
    (
        Intent.ARTIFACT_GENERATION,
        (
            ("artifact:artifact_terms", _ARTIFACT_TERMS_RE, 0.6),
            ("artifact:document_terms", _DOCUMENT_TERMS_RE, 0.45),
            ("artifact:creation_verb", _CREATION_VERB_RE, 0.2),
        ),
    ),
    (
        Intent.RAG_QA,
        (
            ("rag:source_terms", _SOURCE_TERMS_RE, 0.45),
            ("rag:topic_terms", _TOPIC_TERMS_RE, 0.3),
            ("rag:attribution_terms", _ATTRIBUTION_TERMS_RE, 0.3),
            ("rag:question_form", _QUESTION_FORM_RE, 0.2),
            ("rag:interrogative", _INTERROGATIVE_RE, 0.15),
        ),
    ),
    (
        Intent.GENERAL,
        (
            ("general:greeting", _GREETING_RE, 0.6),
            ("general:meta", _META_RE, 0.6),
            ("general:courtesy", _COURTESY_RE, 0.5),
        ),
    ),
)

#: Tie-break order - more specific pathways win.
_INTENT_PRIORITY: dict[Intent, int] = {
    Intent.SHIP30FOR30: 3,
    Intent.ARTIFACT_GENERATION: 2,
    Intent.RAG_QA: 1,
    Intent.GENERAL: 0,
}

_FALLBACK_SIGNAL = "general:low_signal"


def references_lenny_sources(text: str) -> bool:
    """True when a request explicitly names Lenny's Podcast/transcripts as a source."""
    return bool(_SOURCE_TERMS_RE.search(text or ""))


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Outcome of one classification pass."""

    intent: Intent
    confidence: float
    classifier: str
    signals: tuple[str, ...] = ()
    secondary_intents: tuple[Intent, ...] = ()


class HeuristicIntentClassifier:
    """Deterministic signal-scoring classifier."""

    name = CLASSIFIER_HEURISTIC

    def classify(self, text: str) -> ClassificationResult:
        prompt = (text or "").strip()
        scores: dict[Intent, float] = {}
        signals: dict[Intent, list[str]] = {}

        for intent, rules in _SIGNAL_RULES:
            matched = [code for code, pattern, _ in rules if pattern.search(prompt)]
            if not matched:
                continue
            weights = {code: weight for code, _, weight in rules}
            scores[intent] = min(1.0, sum(weights[code] for code in matched))
            signals[intent] = matched

        ranked = sorted(
            scores,
            key=lambda intent: (scores[intent], _INTENT_PRIORITY[intent]),
            reverse=True,
        )
        if not ranked or scores[ranked[0]] < MIN_PRIMARY_SCORE:
            return ClassificationResult(
                intent=Intent.GENERAL,
                confidence=LOW_SIGNAL_CONFIDENCE,
                classifier=self.name,
                signals=(_FALLBACK_SIGNAL,),
                secondary_intents=tuple(intent for intent in ranked if intent is not Intent.GENERAL),
            )

        primary = ranked[0]
        secondary = tuple(
            intent
            for intent in ranked[1:]
            if intent is not Intent.GENERAL and scores[intent] >= SECONDARY_SCORE
        )
        return ClassificationResult(
            intent=primary,
            confidence=round(min(MAX_CONFIDENCE, scores[primary]), 2),
            classifier=self.name,
            signals=tuple(signals[primary]),
            secondary_intents=secondary,
        )


LLM_CLASSIFICATION_INSTRUCTION = (
    "You label a single user request with exactly one intent label.\n"
    "Allowed labels:\n"
    '- "rag_qa": the request asks about product, growth or startup topics, or about what '
    "Lenny's Podcast guests said, advised or recommended.\n"
    '- "ship30for30": the request asks for an essay, article or long-form written piece to be '
    "written (typically around 1250 words).\n"
    '- "artifact_generation": the request asks for a document, markdown file, landing page, '
    "web page or HTML/CSS artifact to be produced.\n"
    '- "general": greetings, small talk, meta questions about the assistant, or anything else.\n'
    "Reply with JSON only, no explanation and no extra text:\n"
    '{"intent": "<label>", "confidence": <number between 0 and 1>}'
)


class LLMIntentClassifier:
    """Optional provider-backed classifier used when LLM-assisted routing is on."""

    name = CLASSIFIER_LLM

    def __init__(self, client: BaseLLMClient, *, max_tokens: int = 64) -> None:
        self._client = client
        self._max_tokens = max_tokens

    async def classify(self, text: str, *, capabilities: tuple[str, ...] = ()) -> ClassificationResult:
        prompt = (text or "").strip()
        hint = ""
        if capabilities:
            hint = f"\nCapabilities currently registered: {', '.join(sorted(capabilities))}."

        response = await self._client.generate(
            [
                LLMMessage(role="user", content=f"User request:\n{prompt}{hint}\n\nJSON label:"),
            ],
            system=LLM_CLASSIFICATION_INSTRUCTION,
            max_tokens=self._max_tokens,
            temperature=0.0,
        )
        return self._parse(response.text)

    def _parse(self, raw: str) -> ClassificationResult:
        payload = extract_json_object(raw)
        if payload is None:
            logger.warning("LLM intent classification returned no JSON object")
            raise AgentClassificationError(
                "The configured provider did not return a JSON intent label.",
            )

        label = str(payload.get("intent", "")).strip().lower()
        try:
            intent = Intent(label)
        except ValueError:
            logger.warning("LLM intent classification returned an unknown label")
            raise AgentClassificationError(
                f"The configured provider returned an unknown intent label '{sanitize_error_text(label, limit=40)}'.",
            ) from None

        confidence = _coerce_confidence(payload.get("confidence"))
        if confidence is None:
            logger.warning("LLM intent classification returned no usable confidence")
            raise AgentClassificationError("The configured provider did not return a usable confidence value.")

        return ClassificationResult(
            intent=intent,
            confidence=confidence,
            classifier=self.name,
            signals=("llm:provider_label",),
        )


def _coerce_confidence(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number or number < 0.0:  # NaN or negative
        return None
    return round(min(1.0, number), 2)


__all__ = [
    "CLASSIFIER_HEURISTIC",
    "CLASSIFIER_LLM",
    "LLM_CLASSIFICATION_INSTRUCTION",
    "ClassificationResult",
    "HeuristicIntentClassifier",
    "LLMIntentClassifier",
    "references_lenny_sources",
]
