# ZeroWall Dashboard (Next.js)

Operator console for the ZeroWall MTD defense loop. It renders live state from
the **ZeroWall Core API** (`core/orchestrator/api_server.py`, port `9000`):

- exploit success rate **before vs after** mutation (RAPIDS analytics)
- defense-cycle count + latency (mean / p95)
- the **Mutation Planner cascade** (NeMo LLM → learned MLP → Triton → deterministic) and which tier last fired
- DGX service health (Triton / vLLM / NeMo planner)
- a **Trigger Defense Cycle** button that POSTs a simulated attack to `/defend`
- recent cycles with action (deploy / reject / rollback) and winner

## Run (dev)

```bash
# 1. start the Core API (repo root)
python -m core.orchestrator.api_server          # serves :9000

# 2. start the dashboard
cd frontend
npm install
ZEROWALL_API_URL=http://localhost:9000 npm run dev   # http://localhost:3000
```

The browser calls `/api/*`, which Next rewrites to `ZEROWALL_API_URL` (see
`next.config.mjs`) — no CORS juggling, and the backend host is configurable for
compose / DGX deployments.

## Run (docker-compose)

The `dashboard-next` service in the repo `docker-compose.yml` builds this image
and points `ZEROWALL_API_URL` at the `zerowall-core` service.
