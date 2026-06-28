"""Triage output schema — the artifact the system produces.

A `TriageCard` is what a support engineer actually wants on their screen: the
failure category, a confidence, the *specific* evidence (step indices + quoted
lines), a root-cause hypothesis, who owns the fix, the recommended action, and a
prevention note for the whole class. It is designed to be both human-readable
and escalation-ready (it contains exactly the "complete technical context" the
job description asks engineers to attach when escalating).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agent_triage.taxonomy.categories import TAXONOMY_VERSION, Owner


class Evidence(BaseModel):
    """A single piece of grounding: which step, and the line that matters."""

    step_index: int
    excerpt: str
    why: str = ""  # why this excerpt supports the classification


class CategoryScore(BaseModel):
    """One entry in a multi-label classification result."""

    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "llm"  # "rule" | "llm"


class TriageCard(BaseModel):
    """The full triage result for one agent run."""

    run_id: str
    task_id: str
    agent: str
    model: str | None = None

    # classification
    primary_category: str
    secondary_category: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    classifier: str = "llm"  # "rule" | "llm" | "hybrid"

    # multi-label: all categories with non-trivial confidence (>= 0.2)
    # Populated by the LLM path when the run shows concurrent failure modes.
    all_categories: list[CategoryScore] = Field(default_factory=list)

    # human correction (set via POST /cards/{run_id}/correct)
    human_label: str | None = None
    human_note: str | None = None

    # explanation
    root_cause: str
    evidence: list[Evidence] = Field(default_factory=list)

    # action (seeded from taxonomy, refined per-case)
    owner: Owner
    recommended_action: str
    prevention: str
    fix_suggestion: str | None = None  # concrete scaffold-level fix for this category

    # provenance / reproducibility
    taxonomy_version: str = TAXONOMY_VERSION
    provider: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_markdown(self) -> str:
        """Render the card as a portable playbook entry / escalation note."""
        lines = [
            f"# Triage: {self.task_id}  ·  `{self.primary_category}`",
            "",
            f"- **Run**: `{self.run_id}`  ·  **Agent**: {self.agent}"
            + (f"  ·  **Model**: {self.model}" if self.model else ""),
            f"- **Confidence**: {self.confidence:.0%}  ·  **Classifier**: {self.classifier}",
            f"- **Owner**: `{self.owner.value}`",
        ]
        if self.secondary_category:
            lines.append(f"- **Secondary**: `{self.secondary_category}`")
        if self.all_categories:
            cats = ", ".join(f"`{c.category}` ({c.confidence:.0%})" for c in self.all_categories)
            lines.append(f"- **All categories**: {cats}")
        if self.human_label:
            note = f" — {self.human_note}" if self.human_note else ""
            lines.append(f"- **Human correction**: `{self.human_label}`{note}")
        lines += [
            "",
            "## Root cause",
            self.root_cause,
            "",
            "## Evidence",
        ]
        if self.evidence:
            for e in self.evidence:
                lines.append(f"- **step {e.step_index}**: `{e.excerpt.strip()[:200]}`")
                if e.why:
                    lines.append(f"  - {e.why}")
        else:
            lines.append("- _No specific step evidence captured._")
        lines += [
            "",
            "## Recommended action",
            self.recommended_action,
            "",
            "## Prevention (class-level)",
            self.prevention,
            "",
            f"_taxonomy {self.taxonomy_version} · {self.provider} · "
            f"{self.created_at.isoformat()}_",
        ]
        return "\n".join(lines)
