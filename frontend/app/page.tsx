"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Analytics,
  type CycleRow,
  type Planner,
  type Status,
} from "@/lib/api";

const ATTACKS = [
  { endpoint: "/data", payload_type: "path-traversal" },
  { endpoint: "/run", payload_type: "command-injection" },
  { endpoint: "/search", payload_type: "sql-injection" },
];

function StatusDot({ on }: { on?: boolean }) {
  return <span className={`dot ${on ? "on" : "off"}`} />;
}

export default function Page() {
  const [status, setStatus] = useState<Status | null>(null);
  const [planner, setPlanner] = useState<Planner | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [cycles, setCycles] = useState<CycleRow[]>([]);
  const [attackIdx, setAttackIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, p, a, c] = await Promise.allSettled([
        api.status(),
        api.planner(),
        api.analytics(),
        api.cycles(),
      ]);
      if (s.status === "fulfilled") setStatus(s.value);
      if (p.status === "fulfilled") setPlanner(p.value);
      if (a.status === "fulfilled") setAnalytics(a.value);
      if (c.status === "fulfilled") setCycles(c.value.cycles ?? []);
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const runDefense = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.defend(ATTACKS[attackIdx]);
      await refresh();
    } catch (e) {
      setErr(`Defense cycle failed — is the Core API on :9000 up? (${e})`);
    } finally {
      setBusy(false);
    }
  };

  const ex = analytics?.exploit_rate;
  const lat = analytics?.cycle_latency;
  const cand = analytics?.candidates;
  const backend = analytics?.rapids_backend ?? "—";
  const isGpu = backend.toLowerCase().includes("gpu");
  const rolling = analytics?.rolling_exploit_rate ?? [];

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>🛡 ZeroWall</h1>
          <div className="sub">Generative AI Firewall · NVIDIA DGX Spark · Moving Target Defense</div>
        </div>
        <span className={`backend-badge ${isGpu ? "" : "cpu"}`}>analytics: {backend}</span>
      </header>

      <div className="grid">
        {/* Exploit rate before/after */}
        <div className="card col-4">
          <h2>Exploit Success Rate</h2>
          <div className="row">
            <span className="label">Before mutation</span>
            <span className="metric small" style={{ color: "var(--red)" }}>
              {ex ? `${Math.round(ex.before * 100)}%` : "—"}
            </span>
          </div>
          <div className="row">
            <span className="label">After mutation</span>
            <span className="metric small" style={{ color: "var(--green)" }}>
              {ex ? `${Math.round(ex.after * 100)}%` : "—"}
            </span>
          </div>
          <div className="row">
            <span className="label">Improvement</span>
            <span className="pill deploy">{ex ? `−${Math.round(ex.improvement * 100)} pts` : "—"}</span>
          </div>
          <div className="spark">
            {(rolling.length ? rolling : [0]).slice(-24).map((v, i) => (
              <div key={i} className="bar" style={{ height: `${Math.max(2, v * 100)}%` }} title={`${Math.round(v * 100)}%`} />
            ))}
          </div>
        </div>

        {/* Cycle stats */}
        <div className="card col-4">
          <h2>Defense Cycles</h2>
          <div className="metric">
            {cand?.total_cycles ?? status?.total_cycles ?? 0}
            <span className="unit">cycles</span>
          </div>
          <div className="row">
            <span className="label">Mean latency</span>
            <span>{lat ? `${lat.mean_s.toFixed(2)} s` : "—"}</span>
          </div>
          <div className="row">
            <span className="label">p95 latency</span>
            <span>{lat ? `${lat.p95_s.toFixed(2)} s` : "—"}</span>
          </div>
          <div className="row">
            <span className="label">Candidates / cycle</span>
            <span>{cand ? cand.avg_per_cycle : "—"}</span>
          </div>
        </div>

        {/* Simulate attack */}
        <div className="card col-4">
          <h2>Simulate Attack</h2>
          <label className="label">Attack scenario</label>
          <select value={attackIdx} onChange={(e) => setAttackIdx(Number(e.target.value))}>
            {ATTACKS.map((a, i) => (
              <option key={i} value={i}>
                {a.payload_type} → {a.endpoint}
              </option>
            ))}
          </select>
          <button className="attack" onClick={runDefense} disabled={busy}>
            {busy ? "Running defense cycle…" : "▶ Trigger Defense Cycle"}
          </button>
          {status?.last_action && (
            <div className="row" style={{ marginTop: 10 }}>
              <span className="label">Last action</span>
              <span className={`pill ${status.last_action}`}>{status.last_action}</span>
            </div>
          )}
          {err && <div className="err">{err}</div>}
        </div>

        {/* Planner cascade */}
        <div className="card col-6">
          <h2>Mutation Planner Cascade</h2>
          {(planner?.tiers ?? []).map((t) => (
            <div key={t.tier} className="tier">
              <StatusDot on={t.active} />
              <span className="name">
                {t.tier}. {t.name}
                {t.name.includes("nemo") && !t.adapter_present && (
                  <span className="label"> · adapter not trained</span>
                )}
              </span>
              {planner?.last_tier_used === t.name.split("-")[0] && <span className="used">← last used</span>}
            </div>
          ))}
          <div className="row" style={{ marginTop: 8 }}>
            <span className="label">Last tier used</span>
            <code className="mono">{planner?.last_tier_used ?? status?.last_planner_tier ?? "—"}</code>
          </div>
        </div>

        {/* Service health */}
        <div className="card col-6">
          <h2>DGX Service Health</h2>
          <div className="row"><span className="label"><StatusDot on={status?.triton_healthy} />Triton (mutation-planner + risk-scorer)</span></div>
          <div className="row"><span className="label"><StatusDot on={status?.vllm_healthy} />vLLM (explanation LLM)</span></div>
          <div className="row"><span className="label"><StatusDot on={status?.nemo_planner_active} />NeMo planner LLM</span></div>
          <div className="row">
            <span className="label">Active version</span>
            <code className="mono">{status?.active_version_hash ?? "—"}</code>
          </div>
        </div>

        {/* Recent cycles */}
        <div className="card col-12">
          <h2>Recent Defense Cycles</h2>
          <table>
            <thead>
              <tr>
                <th>Cycle</th>
                <th>Action</th>
                <th>Winner</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {cycles.length === 0 && (
                <tr><td colSpan={4} className="label">No cycles yet — trigger one above.</td></tr>
              )}
              {cycles.slice().reverse().map((c) => (
                <tr key={c.cycle_id}>
                  <td><code className="mono">{c.cycle_id.slice(0, 8)}</code></td>
                  <td><span className={`pill ${c.action}`}>{c.action}</span></td>
                  <td>{c.winner_id ?? "—"}</td>
                  <td>{c.latency_s != null ? `${c.latency_s.toFixed(2)} s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
