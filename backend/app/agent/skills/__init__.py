"""Executable capabilities of the application agent (Phase 4).

Each module implements one capability behind the Phase 3 :class:`AgentTool`
interface and is registered in the tool registry:

* :mod:`~app.agent.skills.transcript_search` - retrieval over the Phase 2
  knowledge base (``match_transcript_chunks`` through the configured embedding
  model).
* :mod:`~app.agent.skills.grounded_qa` - grounded answers from retrieved evidence.
* :mod:`~app.agent.skills.ship30for30` - the ~1250-word Ship30for30 article.
* :mod:`~app.agent.skills.artifacts` - structured markdown / HTML+CSS artifacts.

Skills run through the existing registry rather than calling each other directly,
which is what makes composition (retrieval + synthesis + artifact) a sequence of
registered capabilities instead of a new orchestration layer.
"""

from app.agent.skills.artifacts import Artifact, ArtifactSkill
from app.agent.skills.base import EvidenceBundle, SkillContext
from app.agent.skills.grounded_qa import TranscriptQASkill
from app.agent.skills.ship30for30 import Ship30For30Skill
from app.agent.skills.transcript_search import TranscriptSearchTool

#: The executable capabilities of this phase, in registration order.
DEFAULT_SKILLS = (
    TranscriptSearchTool,
    TranscriptQASkill,
    Ship30For30Skill,
    ArtifactSkill,
)

__all__ = [
    "DEFAULT_SKILLS",
    "Artifact",
    "ArtifactSkill",
    "EvidenceBundle",
    "Ship30For30Skill",
    "SkillContext",
    "TranscriptQASkill",
    "TranscriptSearchTool",
]
