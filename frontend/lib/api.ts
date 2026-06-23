// ZeroWall dashboard — typed client for the Core API (proxied via /api/*).

export type Status = {
  active_version_hash?: string;
  total_cycles?: number;
  last_action?: string | null;
  last_winner?: string | null;
  last_cycle_latency_s?: number | null;
  triton_healthy?: boolean;
  vllm_healthy?: boolean;
  nemo_planner_active?: boolean;
  nemo_adapter_present?: boolean;
  last_planner_tier?: string;
  status?: string;
};

export type PlannerTier = {
  tier: number;
  name: string;
  active: boolean;
  adapter_present?: boolean;
  trained_at?: string | null;
};

export type Planner = { tiers: PlannerTier[]; last_tier_used?: string };

export type Analytics = {
  exploit_rate?: { before: number; after: number; improvement: number; backend?: string };
  cycle_latency?: { mean_s: number; p95_s: number; count: number; backend?: string };
  candidates?: { total_candidates: number; avg_per_cycle: number; total_cycles: number };
  rolling_exploit_rate?: number[];
  rapids_backend?: string;
};

export type CycleRow = {
  cycle_id: string;
  action: string;
  winner_id: string | null;
  latency_s: number | null;
};

const j = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
};

export const api = {
  status: () => j<Status>("/status"),
  planner: () => j<Planner>("/planner"),
  analytics: () => j<Analytics>("/analytics"),
  cycles: () => j<{ total: number; cycles: CycleRow[] }>("/cycles"),
  defend: (attack_context: Record<string, unknown>) =>
    j<{ cycle_id: string; action: string; winner_id: string | null; cycle_latency_s: number }>(
      "/defend",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attack_context }),
      },
    ),
};
