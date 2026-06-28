// Data layer: types mirroring the backend, plus a client that talks to the API
// and falls back to bundled demo data so the deployed site works standalone.

export type Owner =
  | "task_author"
  | "environment"
  | "agent_framework"
  | "model"
  | "unknown";

export interface Evidence {
  step_index: number;
  excerpt: string;
  why: string;
}

export interface TriageCard {
  run_id: string;
  task_id: string;
  agent: string;
  model: string | null;
  primary_category: string;
  secondary_category: string | null;
  confidence: number;
  classifier: "rule" | "llm" | "hybrid";
  root_cause: string;
  evidence: Evidence[];
  owner: Owner;
  recommended_action: string;
  prevention: string;
  fix_suggestion: string | null;
  taxonomy_version: string;
  provider: string;
}

export interface BatchResponse {
  count: number;
  cards: TriageCard[];
  distribution: Record<string, number>;
  owner_distribution: Record<string, number>;
  mock_mode: boolean;
}

export interface TaxonomyCategory {
  code: string;
  name: string;
  definition: string;
  owner: Owner;
  signals: string[];
  recommended_action: string;
  prevention: string;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE && process.env.NEXT_PUBLIC_API_BASE.length > 0
    ? process.env.NEXT_PUBLIC_API_BASE
    : null;

// Category display metadata: stable order + color tokens keyed by ownership.
export const CATEGORY_ORDER = [
  "SCOPING",
  "ENVIRONMENT",
  "CONTEXT_RETRIEVAL",
  "REASONING",
  "VERIFICATION",
  "TOOL_USE",
  "RESOURCE_LIMIT",
  "IMPLEMENTATION_STALL",
  "INFRA_ERROR",
  "OTHER",
] as const;

export const OWNER_LABELS: Record<Owner, string> = {
  task_author: "Task author",
  environment: "Environment / infra",
  agent_framework: "Agent framework",
  model: "Model",
  unknown: "Unclassified",
};

// Accent color per ownership — the dashboard's color logic encodes *who fixes it*.
export const OWNER_COLORS: Record<Owner, string> = {
  task_author: "#e0a458", // amber — educate the user
  environment: "#5ec8c8", // teal — infra
  agent_framework: "#7c9eff", // indigo — escalate to eng
  model: "#c77dff", // violet — model/route
  unknown: "#8a8f98", // grey
};

export async function fetchBatch(): Promise<BatchResponse> {
  if (API_BASE) {
    try {
      // /triage/demo is a public GET endpoint — the API classifies the bundled
      // demo runs once at startup and serves the cached result. No auth required.
      const res = await fetch(`${API_BASE}/triage/demo`);
      if (res.ok) return (await res.json()) as BatchResponse;
    } catch {
      // fall through to bundled demo cards
    }
  }
  return demoBatch();
}

export async function fetchTaxonomy(): Promise<TaxonomyCategory[]> {
  if (API_BASE) {
    try {
      const res = await fetch(`${API_BASE}/taxonomy`);
      if (res.ok) {
        const body = await res.json();
        return body.categories as TaxonomyCategory[];
      }
    } catch {
      // fall through
    }
  }
  const mod = await import("./demoData");
  return mod.DEMO_TAXONOMY;
}

async function loadDemoRuns(): Promise<unknown[]> {
  const mod = await import("./demoData");
  return mod.DEMO_RUNS;
}

async function demoBatch(): Promise<BatchResponse> {
  const mod = await import("./demoData");
  const cards = mod.DEMO_CARDS;
  const distribution: Record<string, number> = {};
  const owner_distribution: Record<string, number> = {};
  for (const c of cards) {
    distribution[c.primary_category] = (distribution[c.primary_category] || 0) + 1;
    owner_distribution[c.owner] = (owner_distribution[c.owner] || 0) + 1;
  }
  return {
    count: cards.length,
    cards,
    distribution,
    owner_distribution,
    mock_mode: true,
  };
}
