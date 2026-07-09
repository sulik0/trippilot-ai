# TripPilot AI Offline Evals

This directory contains small deterministic evaluation cases for the resume project.

The goal is not to benchmark model quality. The goal is to keep core agent contracts stable without calling real LLM, network, weather, or vector database services.

## Dataset

- `agent_contract_cases.jsonl` stores one JSON object per case.
- Each case has `id`, `agent`, `input`, and `expected`.
- Tests load these cases and pair them with mock model outputs or mocked tool methods.

## Covered Paths

- Intent routing and schedule shape.
- Event extraction output shape.
- Preference append and replace behavior.
- RAG intent routing through `rag_knowledge`.
- Weather query classification for real-time information.

## Run

```bash
.venv313/bin/python -m pytest tests/test_agent_contracts.py -q
```
