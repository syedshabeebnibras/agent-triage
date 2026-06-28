"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CATEGORY_ORDER,
  OWNER_COLORS,
  OWNER_LABELS,
  type BatchResponse,
  type Owner,
  type TriageCard,
  fetchBatch,
} from "@/lib/api";
import { CardModal } from "@/components/CardModal";

// which owner a category maps to (kept in the client for color logic)
const CATEGORY_OWNER: Record<string, Owner> = {
  SCOPING: "task_author",
  ENVIRONMENT: "environment",
  CONTEXT_RETRIEVAL: "agent_framework",
  REASONING: "model",
  VERIFICATION: "agent_framework",
  TOOL_USE: "agent_framework",
  RESOURCE_LIMIT: "agent_framework",
  IMPLEMENTATION_STALL: "agent_framework",
  INFRA_ERROR: "environment",
  OTHER: "unknown",
};

const CATEGORY_LABEL: Record<string, string> = {
  SCOPING: "Scoping",
  ENVIRONMENT: "Environment",
  CONTEXT_RETRIEVAL: "Context retrieval",
  REASONING: "Reasoning",
  VERIFICATION: "Verification",
  TOOL_USE: "Tool use",
  RESOURCE_LIMIT: "Resource limit",
  IMPLEMENTATION_STALL: "Implementation stall",
  INFRA_ERROR: "Infra error",
  OTHER: "Other",
};

export default function Page() {
  const [data, setData] = useState<BatchResponse | null>(null);
  const [selected, setSelected] = useState<TriageCard | null>(null);
  const [loaded, setLoaded] = useState(false);

  // filter / search state
  const [filterCat, setFilterCat] = useState<string>("");
  const [filterOwner, setFilterOwner] = useState<Owner | "">("");
  const [filterMinConf, setFilterMinConf] = useState<number>(0);
  const [search, setSearch] = useState<string>("");

  useEffect(() => {
    fetchBatch().then((d) => {
      setData(d);
      // small delay so the distribution bars animate in
      requestAnimationFrame(() => setLoaded(true));
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSelected(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const maxCount = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, ...Object.values(data.distribution));
  }, [data]);

  const total = data?.count ?? 0;
  const escalations = useMemo(() => {
    if (!data) return 0;
    return data.cards.filter(
      (c) => CATEGORY_OWNER[c.primary_category] === "agent_framework"
    ).length;
  }, [data]);
  const ruleShare = useMemo(() => {
    if (!data || data.cards.length === 0) return 0;
    const rules = data.cards.filter((c) => c.classifier === "rule").length;
    return Math.round((rules / data.cards.length) * 100);
  }, [data]);
  const ownersSeen = useMemo(() => {
    if (!data) return [];
    return Object.keys(data.owner_distribution) as Owner[];
  }, [data]);

  const filteredCards = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase().trim();
    return data.cards.filter((c) => {
      if (filterCat && c.primary_category !== filterCat) return false;
      if (filterOwner && CATEGORY_OWNER[c.primary_category] !== filterOwner) return false;
      if (c.confidence < filterMinConf) return false;
      if (q && !c.task_id.toLowerCase().includes(q) &&
          !c.run_id.toLowerCase().includes(q) &&
          !c.root_cause.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data, filterCat, filterOwner, filterMinConf, search]);

  return (
    <>
      <header className="masthead">
        <div className="masthead-inner">
          <div className="brand">
            <span className="brand-mark">
              agent<span className="dot">·</span>triage
            </span>
            <span className="brand-sub">v0.2 · taxonomy 0.2.0</span>
          </div>
          <nav className="masthead-meta">
            <a href="#distribution">distribution</a>
            <a href="#runs">runs</a>
            <a
              href="https://github.com/syedshabeebnibras/agent-triage"
              target="_blank"
              rel="noreferrer"
            >
              github ↗
            </a>
          </nav>
        </div>
      </header>

      <div className="wrap">
        <section className="hero">
          <div className="eyebrow">root-cause analysis for autonomous coding agents</div>
          <h1>
            When an agent run fails, the question is not <em>did it fail</em>.
            It is <em>why</em>, <em>who fixes it</em>, and <em>how to stop the
            whole class</em>.
          </h1>
          <p>
            Agent Triage ingests a failed Devin, OpenHands, or SWE-agent run,
            classifies the failure against an ownership-tagged taxonomy, grounds the
            verdict in specific trajectory steps, and produces a reusable playbook card.
            That card is the exact artifact a support engineer attaches when escalating to
            engineering or educating a customer.
          </p>
          {data?.mock_mode ? (
            <div className="banner">
              <span className="pulse" />
              Sample of real triaged runs (offline fallback). Live verdicts come
              from the FastAPI backend with a live model.
            </div>
          ) : null}
        </section>

        <section className="block">
          <div className="section-head">
            <span className="section-num">01</span>
            <h2>Run summary</h2>
            <span className="hint">batch of {total} failed runs</span>
          </div>
          <div className="stats">
            <div className="stat">
              <div className="v">{total}</div>
              <div className="l">failed runs analyzed</div>
            </div>
            <div className="stat">
              <div className="v" style={{ color: "var(--c-agent)" }}>
                {escalations}
              </div>
              <div className="l">→ escalate to eng</div>
            </div>
            <div className="stat">
              <div className="v">{ruleShare}%</div>
              <div className="l">classified by rules (free)</div>
            </div>
            <div className="stat">
              <div className="v">
                {Object.keys(data?.distribution ?? {}).length}
              </div>
              <div className="l">distinct failure modes</div>
            </div>
          </div>
        </section>

        <section className="block" id="distribution">
          <div className="section-head">
            <span className="section-num">02</span>
            <h2>Failure distribution</h2>
            <span className="hint">color = who owns the fix</span>
          </div>
          <div className="dist">
            {CATEGORY_ORDER.map((cat) => {
              const count = data?.distribution[cat] ?? 0;
              const owner = CATEGORY_OWNER[cat];
              const color = OWNER_COLORS[owner];
              const pct = loaded ? (count / maxCount) * 100 : 0;
              return (
                <div className="dist-row" key={cat}>
                  <div className="dist-label">
                    <span
                      className="dist-swatch"
                      style={{ background: color }}
                    />
                    {CATEGORY_LABEL[cat]}
                  </div>
                  <div className="dist-track">
                    <div
                      className="dist-fill"
                      style={{
                        width: `${pct}%`,
                        background: color,
                        opacity: count === 0 ? 0.18 : 0.85,
                      }}
                    />
                  </div>
                  <div className="dist-count">{count}</div>
                </div>
              );
            })}
          </div>

          <div className="owners">
            {(Object.keys(OWNER_LABELS) as Owner[])
              .filter((o) => ownersSeen.includes(o))
              .map((o) => (
                <div className="owner-chip" key={o}>
                  <span className="sq" style={{ background: OWNER_COLORS[o] }} />
                  {OWNER_LABELS[o]}
                  <span style={{ color: "var(--text-faint)" }}>
                    ({data?.owner_distribution[o] ?? 0})
                  </span>
                </div>
              ))}
          </div>
        </section>

        <section className="block" id="runs">
          <div className="section-head">
            <span className="section-num">03</span>
            <h2>Triaged runs</h2>
            <span className="hint">
              {filteredCards.length} of {data?.count ?? 0} — click a card for evidence + playbook
            </span>
          </div>

          <div className="filters">
            <input
              className="filter-search"
              type="search"
              placeholder="Search task ID, run ID, or root cause..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className="filter-select"
              value={filterCat}
              onChange={(e) => setFilterCat(e.target.value)}
            >
              <option value="">All categories</option>
              {CATEGORY_ORDER.map((cat) => (
                <option key={cat} value={cat}>{CATEGORY_LABEL[cat]}</option>
              ))}
            </select>
            <select
              className="filter-select"
              value={filterOwner}
              onChange={(e) => setFilterOwner(e.target.value as Owner | "")}
            >
              <option value="">All owners</option>
              {(Object.keys(OWNER_LABELS) as Owner[]).map((o) => (
                <option key={o} value={o}>{OWNER_LABELS[o]}</option>
              ))}
            </select>
            <label className="filter-conf">
              <span>Conf &ge;{Math.round(filterMinConf * 100)}%</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={filterMinConf}
                onChange={(e) => setFilterMinConf(parseFloat(e.target.value))}
              />
            </label>
            {(filterCat || filterOwner || filterMinConf > 0 || search) ? (
              <button
                className="filter-reset"
                onClick={() => { setFilterCat(""); setFilterOwner(""); setFilterMinConf(0); setSearch(""); }}
              >
                Clear filters
              </button>
            ) : null}
          </div>

          <div className="cards">
            {filteredCards.map((card) => {
              const owner = CATEGORY_OWNER[card.primary_category];
              const color = OWNER_COLORS[owner];
              return (
                <article
                  className="card"
                  key={card.run_id}
                  onClick={() => setSelected(card)}
                >
                  <div className="card-top" style={{ borderLeftColor: color }}>
                    <span className="card-cat" style={{ color }}>
                      {card.primary_category}
                    </span>
                    <span className="card-conf">
                      <span className="tag">{card.classifier}</span>
                      {Math.round(card.confidence * 100)}%
                    </span>
                  </div>
                  <div className="card-body">
                    <div className="card-task">{card.task_id}</div>
                    <div className="card-cause">{card.root_cause}</div>
                  </div>
                  <div className="card-foot">
                    <span>{OWNER_LABELS[owner]}</span>
                    <span>{card.evidence.length} evidence →</span>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <footer>
          Agent Triage is a failure triage system for autonomous coding agents.
          Taxonomy v0.2.0, empirically validated on 30 real OpenHands and SWE-bench
          runs (κ=1.000). Backend: Python and FastAPI with deterministic signals,
          model-agnostic LLM classification, and Cohen&apos;s kappa evaluation.{" "}
          <a
            href="https://github.com/syedshabeebnibras/agent-triage"
            target="_blank"
            rel="noreferrer"
          >
            Source and runbook
          </a>
        </footer>
      </div>

      <CardModal card={selected} onClose={() => setSelected(null)} />
    </>
  );
}
