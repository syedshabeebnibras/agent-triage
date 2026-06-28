"use client";

import { OWNER_COLORS, OWNER_LABELS, type TriageCard } from "@/lib/api";

export function CardModal({
  card,
  onClose,
}: {
  card: TriageCard | null;
  onClose: () => void;
}) {
  if (!card) return null;
  const accent = OWNER_COLORS[card.owner];

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head" style={{ borderLeftColor: accent }}>
          <h3>
            <span style={{ color: accent }}>{card.primary_category}</span>
            {card.secondary_category ? (
              <span style={{ color: "var(--text-faint)" }}>
                {"  ·  +" + card.secondary_category}
              </span>
            ) : null}
          </h3>
          <button className="modal-close" onClick={onClose}>
            esc ✕
          </button>
        </div>

        <div className="modal-body">
          <dl className="kv">
            <dt>task</dt>
            <dd>{card.task_id}</dd>
            <dt>run</dt>
            <dd>{card.run_id}</dd>
            <dt>agent / model</dt>
            <dd>
              {card.agent}
              {card.model ? " · " + card.model : ""}
            </dd>
            <dt>owner</dt>
            <dd style={{ color: accent }}>{OWNER_LABELS[card.owner]}</dd>
            <dt>confidence</dt>
            <dd>{Math.round(card.confidence * 100)}%</dd>
            <dt>classifier</dt>
            <dd>{card.classifier}</dd>
          </dl>

          <h4>Root cause</h4>
          <p className="cause">{card.root_cause}</p>

          <h4>Evidence</h4>
          <div className="evidence">
            {card.evidence.length === 0 ? (
              <div className="ev">
                <div className="ev-excerpt">No specific step evidence captured.</div>
              </div>
            ) : (
              card.evidence.map((e, i) => (
                <div className="ev" key={i} style={{ borderLeftColor: accent }}>
                  <div className="ev-step" style={{ color: accent }}>
                    step {e.step_index}
                  </div>
                  <div className="ev-excerpt">{e.excerpt}</div>
                  {e.why ? <div className="ev-why">{e.why}</div> : null}
                </div>
              ))
            )}
          </div>

          <h4>Recommended action</h4>
          <div className="action-box">{card.recommended_action}</div>

          <h4>Prevention (class level)</h4>
          <div className="action-box">{card.prevention}</div>

          {card.fix_suggestion ? (
            <>
              <h4>Scaffold fix</h4>
              <div className="action-box action-box--fix">{card.fix_suggestion}</div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
