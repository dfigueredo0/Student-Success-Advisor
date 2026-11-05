# ADR 0001: qwen3:14b behind `local-llm` for routing and slot filling

- Status: accepted (pending AI Security review of the gateway change)
- Date: 2026-11-05

## Context

The model does two jobs in this codebase: it routes each message to an intent
(`orchestrator/router.py`, JSON-schema-constrained) and fills scaffold fields from the
conversation (`orchestrator/followup.py`). Answers are templated from tool results, so
"tool-calling reliability" here means routing accuracy. Both jobs use the `local-llm` alias
with the router's gateway key.

Until now `local-llm` was `qwen3:1.7b`, chosen to run on CPU. Ollama now runs on the dev GPU
(RX 9070 XT, 16 GB, ROCm; commit 68b1301), so larger models fit.

## Method

- Gold set `data/gold/routing.jsonl`: 105 items, including 10 mid-question replies and
  9 `drop_course` items. Prompt `router_intent@4`, threshold 0.6.
- `eval/harness.py --mode full` (production path: hand-offs, whole-message patterns, then the
  model) and `--mode model` (model on every item), with `--model <alias>` through temporary
  `bakeoff-*` gateway aliases (removed after this ADR).
- The router's own request settings: `temperature 0`, `reasoning_effort "none"`,
  `max_tokens 64`, paced under the key's 60 rpm.
- Latency is the gateway round trip per call, measured after a warm-up call. VRAM comes from
  `ollama ps`.
- Decision rule, fixed before the runs: pick the fastest candidate with full-path accuracy
  ≥ 90%, misroutes ≤ 3%, no unparseable replies and p95 ≤ 1.5 s. Keep qwen3:1.7b unless a
  candidate beats it by ≥ 2 points.

Results are in `eval/results/routing-2026-11-05-{full,model}-bakeoff-*.json`. The two
`*-bakeoff-qwen3-1.7b` files were run as `local-llm` while it still pointed at qwen3:1.7b.

## Results

| Model                                              | Full accuracy                                                 | Misroutes (full) | Model-only accuracy | p50 / p95              | Cold load       | VRAM             |
| -------------------------------------------------- | ------------------------------------------------------------- | ---------------- | ------------------- | ---------------------- | --------------- | ---------------- |
| qwen3:1.7b                                         | 90%                                                           | 10 (9%)          | 84%                 | 147 / 164 ms           | 1.0 s           | 1.7 GB           |
| qwen3:4b                                           | 92%                                                           | 8 (8%)           | 87%                 | 302 / 321 ms           | 2.0 s           | 3.2 GB           |
| qwen3:8b                                           | 94%                                                           | 6 (6%)           | 89%                 | 293 / 318 ms           | 3.1 s           | 5.6 GB           |
| **qwen3:14b**                                | **96%**                                                 | **4 (4%)** | **92%**       | **475 / 533 ms** | **5.3 s** | **9.7 GB** |
| gpt-oss:20b, router settings                       | every call rejected: HTTP 400 on `reasoning_effort: "none"` |                  |                     |                        |                 |                  |
| gpt-oss:20b, `max_tokens 512`, `reasoning low` | 95%                                                           | 5 (5%)           | not run             | 753 / 1292 ms          | 7.4 s           | ~13 GB           |

None of these runs produced an unparseable reply or a timeout.

- **qwen3:14b's four errors** are R08 (spring electives → `find_courses`), R48 (a career
  question → `find_courses`), R34 ("finish on time if I drop a class") and R53 ("last day to
  drop") → `drop_course`. It made no mid-question errors.
- **qwen3:1.7b's errors** include the misreads behind the `drop_course` attractor and
  `check_eligibility` errors on course-availability questions (R73, R76, R77).
- **CPU vs GPU drift:** the same qwen3:1.7b and prompt scored 95% on CPU and 92% on GPU over the
  same 96 items. Earlier numbers measured on CPU can't be compared with these one to one.

## Decision

Point `local-llm` at **qwen3:14b** (`infra/litellm/config.yml`, `OLLAMA_MODEL` in compose,
`.env.example` and settings).

This departs from the rule above. No candidate, the incumbent included, met "misroutes ≤ 3%".
qwen3:14b is the best on every quality column, beats qwen3:1.7b by 6 points, and stays under
the latency bar (p95 533 ms vs 1.5 s). gpt-oss:20b comes close on accuracy, but it can't turn
thinking off: it needs 8× the token budget and is 2.4× slower at p95, and it doesn't leave room
for anything else in 16 GB.

## Consequences

- **Slot filling** (`fill_slots`) uses the same alias, so it moves to 14b too. That was not
  measured here: there's no slot-filling gold set yet (planned as the `agent-main` follow-up).
- **Cold load is 5.3 s.** Ollama unloads an idle model after 5 minutes, so the first message
  after a pause waits about 5 s. Warm the model up before a demo. AI Security / infra to
  decide on `OLLAMA_KEEP_ALIVE`.
- **VRAM:** 9.7 GB leaves about 6 GB. A future `agent-main` larger than that can't stay
  resident alongside it, and each swap costs a cold load.
- **Fresh clones:** they pull qwen3:14b (9.3 GB) on `make up`, and the healthcheck's 600 s
  start period has to cover the download. The CPU fallback (`make up GPU=cpu`) is now slow
  (not measured). Use `OLLAMA_MODEL=qwen3:1.7b` together with a matching `config.yml` edit
  on machines without a GPU.
- **Remaining misroutes** need attention, but not by tuning further on these 105 items:

  - `drop_course` vs deadline/graduation questions (R34, R53)
  - course questions answered as topic searches (R08, R48)

  Add held-out items first (interview verbatims, per the Researcher).
