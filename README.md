# No Next Move

> Find where a system has no next move. Show what fails next. Tell you whether to fix it, avoid it, hedge it, monitor it, escalate it, or stress-test it.

---

## What it does

No Next Move is a collapse intelligence platform. It ingests operational data — org charts, process maps, vendor relationships, contracts, system architecture — builds a dependency graph, and runs three engines:

1. **Dependency engine** — finds single points of failure, hidden chokepoints, false redundancy, cycles with no exit
2. **Flow engine** — tracks decision/information/resource/obligation/feedback flows; detects dead ends, broken loops, timing traps
3. **Scenario engine** — runs lawful simulations (node removal, delay injection, vendor outage, approval blockage, etc.)

Each node gets five scores:

| Score | Measures |
|---|---|
| **NNM score** | Overall no-next-move fragility |
| **Hidden constraint** | More critical than surface metrics show |
| **False redundancy** | Apparent alternatives collapse to one bottleneck |
| **Pressure absorption** | Whether stress redistributes or localises |
| **Reversion potential** | Whether value migrates on failure |

Every collapse point gets an action label: **Fix / Avoid / Hedge / Monitor / Escalate / Stress-test / Exploit (lawful)**.

---

## Architecture

```
backend/
  app/
    models/graph.py          — Node, Edge, Graph, CollapsePoint, GraphAnalysis
    engines/
      dependency.py          — NetworkX graph analysis, SPOF, false redundancy
      flow.py                — Flow type analysis, dead ends, timing traps
      scenario.py            — Deterministic scenario simulations
      scoring.py             — Five composite scores per node
      classifier.py          — Action label decision logic
      analyzer.py            — Orchestrator: runs all engines, returns GraphAnalysis
    api/routes.py            — FastAPI endpoints
    utils/ingest.py          — CSV, JSON, org-chart ingest
  tests/

frontend/
  src/
    components/
      CollapseMap.tsx         — Cytoscape.js graph (red/orange/green/purple)
      ActionPanel.tsx         — Collapse points, scores, evidence, reversion targets
      StressSlider.tsx        — Time-to-failure pressure slider
      Toolbar.tsx             — Load demo / upload graph
    store/useStore.ts         — Zustand state
    api/client.ts             — Typed API client

data/samples/
  supply_chain_demo.json      — Built-in demo: supply chain with hidden chokepoints
```

---

## Running locally

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Docker Compose

```bash
docker-compose up
```

---

## API quick reference

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/demo` | Load & analyze built-in supply chain demo |
| POST | `/api/v1/graphs` | Create graph from JSON body |
| POST | `/api/v1/graphs/csv` | Upload CSV edge list |
| POST | `/api/v1/graphs/json` | Upload JSON graph file |
| GET | `/api/v1/graphs` | List all graphs |
| POST | `/api/v1/graphs/{id}/analyze` | Run full analysis |
| POST | `/api/v1/graphs/{id}/simulate` | Run scenario simulation |
| GET | `/api/v1/graphs/{id}/nodes/{nid}/scores` | Per-node scores + action |

### CSV edge list format

```csv
source_id,target_id,edge_type,source_label,target_label,source_type,target_type,weight,reliability,latency
ceo,coo,escalates_to,CEO,COO,person,person,1.0,1.0,4.0
```

Edge types: `depends_on` `approves` `funds` `informs` `blocks` `substitutes` `escalates_to` `governed_by` `timed_before` `contingent_on`

Node types: `person` `team` `function` `process_step` `system` `contract_clause` `vendor` `asset` `decision_gate` `assumption` `narrative`

### Simulation types

`node_removal` `delay_injection` `cost_shock` `assumption_failure` `approval_blockage` `vendor_outage` `clause_invalidation` `leadership_absence` `comms_blackout` `full`

---

## Tests

```bash
cd backend
pytest tests/ -v
```

---

## What's next (Phase 2)

- PostgreSQL + Neo4j persistence
- Document ingestion (PDF/DOCX → clause/obligation extraction via spaCy)
- Workflow log ingest (ticket/ERP events)
- Monte Carlo simulation layer
- Live dashboard with real-time graph updates
- Market/public-data adapters for reversion analysis
