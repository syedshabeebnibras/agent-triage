"""Gold-set handling for evaluation.

A gold set is a collection of runs that a human has labeled with the correct
failure category. It is the ground truth the classifier is measured against.
This is what separates "I built a classifier" from "I built a classifier and
measured that it agrees with humans X% of the time, kappa Y" — the latter is the
claim that earns trust.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from agent_triage.taxonomy.categories import is_valid


class GoldLabel(BaseModel):
    """A human-assigned ground-truth label for one run."""

    run_id: str
    task_id: str
    true_category: str
    labeler: str = "unknown"
    notes: str = ""

    def validate_category(self) -> None:
        if not is_valid(self.true_category):
            raise ValueError(
                f"Gold label for {self.run_id} has invalid category "
                f"{self.true_category!r}"
            )


class GoldSet(BaseModel):
    """A collection of gold labels."""

    labels: list[GoldLabel]
    version: str = "0.1.0"

    def by_run_id(self) -> dict[str, GoldLabel]:
        return {lbl.run_id: lbl for lbl in self.labels}

    def validate_all(self) -> None:
        for lbl in self.labels:
            lbl.validate_category()

    @classmethod
    def from_jsonl(cls, path: str | Path) -> GoldSet:
        labels = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                labels.append(GoldLabel(**json.loads(line)))
        gs = cls(labels=labels)
        gs.validate_all()
        return gs

    def to_jsonl(self, path: str | Path) -> None:
        with open(path, "w") as f:
            for lbl in self.labels:
                f.write(lbl.model_dump_json() + "\n")
