# Traçabilité G.O.A.L. — run 920aec0b

## Résumé

- iterations: 1
- last_error: [Errno 32] Broken pipe
- objective: Test role_mapping extras
- provider: role-mapped
- status: failed
- synthesizer_provider: mock
- variant: A
- verdict: absent

## Événements

### 1 — run_started (2026-07-11T03:05:34.644488+00:00)

```json
{
  "event": "run_started",
  "objective": "Test role_mapping extras",
  "provider": "role-mapped",
  "run_id": "920aec0b",
  "sequence": 1,
  "synthesizer_provider": "mock",
  "timestamp_utc": "2026-07-11T03:05:34.644488+00:00",
  "variant": "A"
}
```

### 2 — error (2026-07-11T03:05:34.656128+00:00)

```json
{
  "error_type": "BrokenPipeError",
  "event": "error",
  "message": "[Errno 32] Broken pipe",
  "run_id": "920aec0b",
  "sequence": 2,
  "timestamp_utc": "2026-07-11T03:05:34.656128+00:00",
  "traceback": "Traceback (most recent call last):\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/orchestrator/cascade_executor.py\", line 129, in run\n    state = self._run_loop(state, audience, constraints, verbose, journal)\n            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/orchestrator/cascade_executor.py\", line 194, in _run_loop\n    print(f\"\\n  Iteration {iteration}/{state.max_iterations} \"\nBrokenPipeError: [Errno 32] Broken pipe\n"
}
```

### 3 — run_finished (2026-07-11T03:05:34.657204+00:00)

```json
{
  "event": "run_finished",
  "iterations": 1,
  "last_error": "[Errno 32] Broken pipe",
  "objective": "Test role_mapping extras",
  "provider": "role-mapped",
  "run_id": "920aec0b",
  "sequence": 3,
  "status": "failed",
  "synthesizer_provider": "mock",
  "timestamp_utc": "2026-07-11T03:05:34.657204+00:00",
  "variant": "A",
  "verdict": "absent"
}
```

### 4 — rag_sync_started (2026-07-11T03:05:34.657555+00:00)

```json
{
  "embedding_host": "ia-general",
  "embedding_model": "bge-m3:latest",
  "event": "rag_sync_started",
  "run_id": "920aec0b",
  "sequence": 4,
  "timeline": "/home/eddie/.goal/runs/920aec0b/timeline.md",
  "timestamp_utc": "2026-07-11T03:05:34.657555+00:00"
}
```

### 5 — rag_sync_failed (2026-07-11T03:05:34.845406+00:00)

```json
{
  "document_id": 2815,
  "error_type": "RuntimeError",
  "event": "rag_sync_failed",
  "message": "Endpoint refusé : les embeddings G.O.A.L. doivent provenir de ia-general",
  "postgres_indexed": true,
  "returncode": 1,
  "run_id": "920aec0b",
  "sequence": 5,
  "timestamp_utc": "2026-07-11T03:05:34.845406+00:00"
}
```

### 6 — error (2026-07-11T03:05:35.038818+00:00)

```json
{
  "error_type": "RagSyncError",
  "event": "error",
  "message": "Endpoint refusé : les embeddings G.O.A.L. doivent provenir de ia-general",
  "run_id": "920aec0b",
  "sequence": 6,
  "timestamp_utc": "2026-07-11T03:05:35.038818+00:00",
  "traceback": "Traceback (most recent call last):\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/orchestrator/cascade_executor.py\", line 129, in run\n    state = self._run_loop(state, audience, constraints, verbose, journal)\n            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/orchestrator/cascade_executor.py\", line 194, in _run_loop\n    print(f\"\\n  Iteration {iteration}/{state.max_iterations} \"\nBrokenPipeError: [Errno 32] Broken pipe\n\nDuring handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/orchestrator/cascade_executor.py\", line 153, in run\n    self.rag_bridge.sync_run(state.run_id, journal=journal)\n  File \"/mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli/src/goal_cascade/rag_bridge.py\", line 135, in sync_run\n    raise RagSyncError(message)\ngoal_cascade.rag_bridge.RagSyncError: Endpoint refusé : les embeddings G.O.A.L. doivent provenir de ia-general\n"
}
```

## Données persistées
