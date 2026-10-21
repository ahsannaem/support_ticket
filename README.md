# Governed Support Ticket Agent

A LangGraph support workflow that classifies a ticket, retrieves context, drafts
and checks a reply, then **waits for a human to approve the exact payload**.
A local Python runner persists checkpoints and demonstrates recovery after a
provider effect commits but its local completion record does not.

This extends the original support agent. It is a single-host reference
implementation, not a deployed enterprise platform. The offline demo uses a
clearly labeled fixture backend. The optional live backend retains Google model
and pgvector integration. **Delivery is always a separate local simulator; no
customer reply, refund, assignment, deadline or status update is sent upstream.**

## What changed

| Before | Now |
|---|---|
| LLM review could return the draft as the final response | Model review is a quality signal; a signed human decision is required |
| Standalone graph compiled without a file-backed checkpointer | CLI uses LangGraph SqliteSaver with a stable thread id |
| Error strings could become drafts or fallback categories | Provider failures stop the node and can resume from the checkpoint |
| Re-embedded the dataset during ticket retrieval | Explicit indexing step with stable document ids |
| Rejected ticket data appended to CSV | Pending/escalated state and node audit records persist in SQLite |
| Import required live credentials; placeholder tests | Core/test installation works without provider credentials |

Agent Server can supply its own persistence; the new local runner makes its
storage and recovery behavior explicit and testable outside that server.

## Quick start: no API keys required

Python 3.11+; commands run from the repository root:

```sh
python -m venv .venv
# Activate .venv using your shell, then:
python -m pip install -c constraints.txt -e ".[dev]"
python -m pytest tests -v
support-ticket --demo submit demo-1 --ticket T-1 --subject "Upload error" --description "The file upload fails."
```

Inspect the proposal and evaluation. The state is `awaiting_approval`, and the
LangGraph next node is `human_review`. Copy its `proposal_hash` only after reading
the full reply and ticket id:

```sh
support-ticket --demo inspect demo-1
support-ticket --demo review demo-1 --actor maya --team support --role reviewer --hash <PASTE_REVIEWED_PROPOSAL_HASH>
support-ticket --demo deliver demo-1
```

`python -m agent.runtime` is equivalent to `support-ticket`. For PowerShell,
replace the hash placeholder with the actual value; do not include angle brackets.
Use `--decision reject` to decline the reply. A contributor, another team, stale
hash, forged receipt or failed evaluation cannot authorize delivery. The CLI is a
**trusted local operator tool**: role/team arguments are not SSO or proof of a
person's identity. A real service must derive them from authenticated claims.

State lives in `.support-data/` by default. Use `--data <directory>` before the
subcommand to select another location. Stop and start a new Python process with
the same directory and thread id to inspect, review or resume saved work:

```sh
support-ticket --demo resume demo-1
```

`submit` rejects reuse of a thread id for different input or backend mode. Repeating
identical submission resumes the existing workflow. `resume` retries an unfinished
node, not an already completed classification/retrieval step. No background queue
or scheduler is implemented; recovery is explicitly driven by the CLI.

## Reproduce the crash boundary

Start and approve a fresh thread, for example `crash-1`. Then:

```sh
support-ticket --demo deliver crash-1 --crash-after-effect
# The test-only fault exits the process with code 86.
support-ticket --demo deliver crash-1
support-ticket --demo inspect crash-1
```

The first process commits a reply to `delivery-simulator.sqlite` and dies before
committing its control-table completion. The second uses the same operation key,
gets the original reply with `deduplicated: true`, and completes the local record.
Repeating delivery after completion returns `already_completed: true`.

The automated suite performs this experiment with actual subprocesses and asserts
that exactly one simulated reply exists. It also exercises concurrent delivery
callers, failed-node resume, human rejection, stale approvals and unsafe context.

This works because the simulator implements idempotent creation. It is **not a
universal exactly-once guarantee** for providers such as email or ticket APIs.
A local transaction cannot undo an external effect. See [the failure model](docs/governance-and-durability.md).

## Governance and evaluation

- Registration requires an owner, team, known tier, tool grant, evaluation suite
  and human gate. Only `reply.propose` is supported.
- A reply accepts exactly `ticket_id` and `body`; no owner, due-date, assignment
  or ticket-status mutation method exists. This restricts API operations, not all
  possible commitment language in free text; the human must review that language.
- Deterministic checks require model-review approval, a nonempty bounded reply,
  public-classified context, no known placeholders and no matched security
  escalation signal. **All must pass.** These narrow checks are not a general DLP,
  prompt-injection detector or factual/tone evaluator.
- The model has no broker or signing capability. The human receipt binds thread,
  ticket/body hash, reviewer, team, decision and expiry using HMAC. Receipt expiry
  applies when accepting the human decision; an already accepted durable approval
  remains deliverable after that window.
- The broker rechecks policy, receipt signature, exact proposal and completion
  identity. It cannot be enabled by a model-generated `approved` string.
- Node start/completion inputs/outputs, human decisions and delivery operations
  are logged locally. These records can contain ticket/context data. Keep the
  directory private, define retention, and review tracing before using real data.

## Optional live model and retrieval

```sh
python -m pip install -c constraints.txt -e ".[live]"
```

Set `GOOGLE_API_KEY`, `GOOGLE_MODEL` (a model your account supports),
`EMBEDDING_MODEL` and `POSTGRES_CONNECTION_STRING`. The runner loads `.env` if
present. Classify the source material explicitly before indexing:

```python
from agent.utils import refresh_rag
refresh_rag("static/dataset", visibility="public")  # only after reviewing the data
```

Then omit `--demo` when creating a new thread. Existing index records without a
visibility label fail closed. Retrieval filters by ticket category and never
re-indexes as a side effect. The live provider interface is contract-tested with
stubs and its dependencies are install-checked; real paid model calls and a live
Postgres connection are **not part of offline CI**.

`docker compose run --rm agent <runtime arguments>` uses the optional live image
and a persistent state volume. Copy `.env.example` to `.env` and set a URL-safe
local database password before Compose. Docker/Compose have not been executed in
the current local validation; this is not a verified deployment.

For local Agent Server development install `.[studio]` and run `langgraph dev`.
That path uses server-managed persistence, not the CLI database. A human resume
must contain a correctly signed receipt using a private `SUPPORT_APPROVAL_KEY`
(at least 32 bytes) supplied only to trusted review tooling/server configuration.
The CLI keeps its own key under its data directory. These are separate runtimes,
not interchangeable stores. A remote review UI/authenticated signing API is not
implemented. The CLI is the exercised approval and delivery interface.

## Checks and boundaries

```sh
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests -v
python -m pip check
```

GitHub Actions runs lint, formatting and the full offline suite on Linux/Windows
and Python 3.11/3.12. Make that status required through repository branch
protection if it must block merges. A workflow file alone does not enforce that.
`constraints.txt` pins the directly tested packages; it is not a complete
cross-platform transitive lock. The obsolete Poetry lock has been removed.

SQLite is appropriate for the local demonstration. Production needs authenticated
reviewers, per-service credentials, Postgres-backed persistence, authorization on
state/trace access, a real provider recovery contract, queue/scheduling, monitoring
and sensitive-data retention controls. A host administrator or malicious Python
plugin can bypass local code boundaries. No production adoption, uptime or cloud
operations are claimed here.
