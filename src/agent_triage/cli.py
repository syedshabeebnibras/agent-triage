"""Command-line interface for Agent Triage.

Examples:
  triage classify data/traces/run.json
  triage batch data/traces/runs.jsonl --out cards.jsonl
  triage eval data/traces/runs.jsonl data/gold/gold.jsonl
  triage calibrate data/traces/runs.jsonl
  triage serve
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent_triage.engine.classifier import TriageClassifier
from agent_triage.eval.gold import GoldSet
from agent_triage.eval.runner import load_runs, run_eval, taxonomy_calibration
from agent_triage.schema.trace import AgentRun

app = typer.Typer(help="Agent Triage: failure triage for coding-agent runs.")
console = Console()


@app.command()
def classify(path: str, markdown: bool = typer.Option(True, help="Print the markdown card")):
    """Classify a single run (JSON file) and print its triage card."""
    with open(path) as f:
        run = AgentRun(**json.load(f))
    card = TriageClassifier().classify(run)
    if markdown:
        console.print(card.to_markdown())
    else:
        console.print_json(card.model_dump_json())


@app.command()
def batch(
    path: str,
    out: str = typer.Option("cards.jsonl", help="Output JSONL of cards"),
):
    """Classify a JSONL of runs and write cards."""
    runs = load_runs(path)
    clf = TriageClassifier()
    cards = [clf.classify(r) for r in runs]
    with open(out, "w") as f:
        for c in cards:
            f.write(c.model_dump_json() + "\n")
    console.print(f"[green]Wrote {len(cards)} cards to {out}[/green]")


@app.command()
def eval(  # noqa: A001 - intentional command name
    runs_path: str,
    gold_path: str,
    out: str = typer.Option("eval_report.json", help="Output report JSON"),
    no_bootstrap: bool = typer.Option(False, help="Skip bootstrap CIs (faster)"),
):
    """Evaluate the classifier against a gold set; print metrics."""
    runs = load_runs(runs_path)
    gold = GoldSet.from_jsonl(gold_path)
    report, details = run_eval(
        runs, gold, TriageClassifier(), bootstrap=not no_bootstrap
    )

    table = Table(title="Triage Evaluation")
    table.add_column("metric")
    table.add_column("value")
    acc_ci = f" [{report.accuracy_ci[0]:.2f}, {report.accuracy_ci[1]:.2f}]" if report.accuracy_ci else ""
    kap_ci = f" [{report.kappa_ci[0]:.2f}, {report.kappa_ci[1]:.2f}]" if report.kappa_ci else ""
    table.add_row("accuracy", f"{report.accuracy:.3f}{acc_ci}")
    table.add_row("cohen's kappa", f"{report.kappa:.3f}{kap_ci}")
    table.add_row("n", str(report.n))
    console.print(table)

    cls_table = Table(title="Per-class")
    for col in ("class", "precision", "recall", "f1", "support"):
        cls_table.add_column(col)
    for name, m in sorted(report.per_class.items()):
        cls_table.add_row(name, f"{m.precision:.2f}", f"{m.recall:.2f}", f"{m.f1:.2f}", str(m.support))
    console.print(cls_table)

    Path(out).write_text(json.dumps({"report": report.to_dict(), "details": details}, indent=2))
    console.print(f"[green]Wrote full report to {out}[/green]")


@app.command()
def calibrate(runs_path: str):
    """Show predicted-category distribution and OTHER rate over a run set."""
    runs = load_runs(runs_path)
    cal = taxonomy_calibration(runs, TriageClassifier())
    console.print_json(json.dumps(cal))


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Run the FastAPI service."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run("agent_triage.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
