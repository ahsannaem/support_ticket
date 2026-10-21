"""Local durable runner and trusted delivery broker, separate from the model."""

import argparse
import contextlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent.backends import DemoBackend, LiveBackend
from agent.governance import (
    Authority,
    PolicyError,
    canonical,
    digest,
    evaluate,
    validate_proposal,
)
from agent.graph import build_graph


class DeliverySimulator:
    """One immutable reply operation; no ticket mutation or arbitrary HTTP API."""

    def __init__(self, path):
        self.path = path
        with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS replies (key TEXT PRIMARY KEY, payload TEXT NOT NULL, reply_id TEXT NOT NULL)"
            )

    def reply(self, key, proposal):
        validate_proposal(proposal)
        with contextlib.closing(
            sqlite3.connect(self.path, isolation_level=None, timeout=30)
        ) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT payload,reply_id FROM replies WHERE key=?", (key,)
            ).fetchone()
            if previous:
                if previous[0] != canonical(proposal):
                    raise PolicyError("Idempotency key reused with a different reply")
                result = {"reply_id": previous[1], "deduplicated": True}
            else:
                result = {
                    "reply_id": "local_" + secrets.token_hex(8),
                    "deduplicated": False,
                }
                db.execute(
                    "INSERT INTO replies VALUES(?,?,?)",
                    (key, canonical(proposal), result["reply_id"]),
                )
            db.commit()
            return result


class Runtime:
    """Single-host CLI runtime. SQLite serializes operations across processes.

    Checkpoints, audit and provider effects have separate transactions. Recovery
    reconciles the checkpoint and stable operation key; it is not a distributed
    transaction. Long model calls hold a local execution lock, limiting throughput.
    """

    def __init__(self, data, demo=False, backend=None):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.mode = "demo" if demo else "live"
        key_path = self.data / "approval.key"
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as out:
                out.write(secrets.token_bytes(32))
                out.flush()
                os.fsync(out.fileno())
        self.authority = Authority(key_path.read_bytes())
        self.control = sqlite3.connect(
            self.data / "control.sqlite", isolation_level=None, timeout=60
        )
        self.control.row_factory = sqlite3.Row
        self.control.executescript(
            "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, mode TEXT NOT NULL, input TEXT NOT NULL); CREATE TABLE IF NOT EXISTS completed (id TEXT PRIMARY KEY, proposal_hash TEXT NOT NULL, result TEXT NOT NULL);"
        )
        with contextlib.closing(
            sqlite3.connect(self.data / "audit.sqlite", isolation_level=None)
        ) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)"
            )
        self.checkpoint_connection = sqlite3.connect(
            self.data / "checkpoints.sqlite", check_same_thread=False
        )
        self.saver = SqliteSaver(self.checkpoint_connection)
        self.graph = build_graph(
            self.saver,
            backend or (DemoBackend() if demo else LiveBackend()),
            self.authority,
            self.audit,
        )
        self.sink = DeliverySimulator(self.data / "delivery-simulator.sqlite")

    def close(self):
        self.checkpoint_connection.close()
        self.control.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextlib.contextmanager
    def exclusive(self):
        self.control.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.control.commit()
        except BaseException:
            self.control.rollback()
            raise

    def audit(self, thread_id, kind, data):
        with contextlib.closing(
            sqlite3.connect(
                self.data / "audit.sqlite", isolation_level=None, timeout=30
            )
        ) as db:
            db.execute(
                "INSERT INTO events(thread_id,at,kind,data) VALUES(?,?,?,?)",
                (thread_id, time.time(), kind, canonical(data)),
            )

    def config(self, thread_id):
        row = self.control.execute(
            "SELECT mode FROM runs WHERE id=?", (thread_id,)
        ).fetchone()
        if row is None or row["mode"] != self.mode:
            raise PolicyError(
                "Unknown thread or backend mode changed; use the original mode"
            )
        return {"configurable": {"thread_id": thread_id}}

    def inspect(self, thread_id):
        snapshot = self.graph.get_state(self.config(thread_id))
        with contextlib.closing(sqlite3.connect(self.data / "audit.sqlite")) as db:
            events = [
                {"seq": r[0], "at": r[1], "kind": r[2], "data": json.loads(r[3])}
                for r in db.execute(
                    "SELECT seq,at,kind,data FROM events WHERE thread_id=? ORDER BY seq",
                    (thread_id,),
                )
            ]
        return {
            "thread_id": thread_id,
            "mode": self.mode,
            "state": snapshot.values,
            "next": list(snapshot.next),
            "audit": events,
        }

    def submit(self, thread_id, ticket):
        if not isinstance(thread_id, str) or not 1 <= len(thread_id) <= 128:
            raise PolicyError("Thread id must contain 1–128 characters")
        if set(ticket) != {"ticket_id", "subject", "description"} or not all(
            isinstance(v, str) and 0 < len(v.strip()) <= 10000 for v in ticket.values()
        ):
            raise PolicyError("Provide only ticket_id, subject and description")
        if len(ticket["ticket_id"]) > 128:
            raise PolicyError("Ticket id must not exceed 128 characters")
        with self.exclusive():
            old = self.control.execute(
                "SELECT * FROM runs WHERE id=?", (thread_id,)
            ).fetchone()
            if old and (old["input"] != canonical(ticket) or old["mode"] != self.mode):
                raise PolicyError("Thread already belongs to another input or backend")
            self.control.execute(
                "INSERT OR IGNORE INTO runs VALUES(?,?,?)",
                (thread_id, self.mode, canonical(ticket)),
            )
        return self.resume(thread_id)

    def resume(self, thread_id):
        with self.exclusive():
            config = self.config(thread_id)
            snapshot = self.graph.get_state(config)
            if snapshot.values and (
                not snapshot.next
                or snapshot.values.get("status") == "awaiting_approval"
            ):
                return self.inspect(thread_id)
            ticket = json.loads(
                self.control.execute(
                    "SELECT input FROM runs WHERE id=?", (thread_id,)
                ).fetchone()[0]
            )
            self.graph.invoke(None if snapshot.values else ticket, config)
            return self.inspect(thread_id)

    def review(self, thread_id, actor, expected_hash, decision="approve"):
        with self.exclusive():
            config = self.config(thread_id)
            snapshot = self.graph.get_state(config)
            state = snapshot.values
            if state.get("status") != "awaiting_approval" or not snapshot.next:
                raise PolicyError("This thread is not awaiting a human decision")
            if (
                state.get("proposal_hash") != expected_hash
                or digest(state["proposal"]) != expected_hash
            ):
                raise PolicyError("Review is stale or the proposal changed")
            if not evaluate(state)["passed"]:
                raise PolicyError("The evaluation gate no longer passes")
            receipt = self.authority.sign(thread_id, state["proposal"], actor, decision)
            self.graph.invoke(Command(resume=receipt), config)
            return self.inspect(thread_id)

    def deliver(self, thread_id, crash_after_effect=False):
        with self.exclusive():
            snapshot = self.graph.get_state(self.config(thread_id))
            state = snapshot.values
            if (
                snapshot.next
                or state.get("status") != "approved"
                or not evaluate(state)["passed"]
            ):
                raise PolicyError(
                    "Delivery requires a completed human approval and passing evaluation"
                )
            proposal = state["proposal"]
            validate_proposal(proposal)
            if proposal != {
                "ticket_id": state.get("ticket_id"),
                "body": state.get("draft", [""])[-1],
            }:
                raise PolicyError(
                    "Evaluated state no longer matches the approved proposal"
                )
            if digest(proposal) != state.get("proposal_hash"):
                raise PolicyError("Approved proposal was modified")
            if (
                self.authority.verify(
                    state.get("receipt"), thread_id, proposal, check_expiry=False
                )
                != "approve"
            ):
                raise PolicyError("A human approval receipt is required")
            completed = self.control.execute(
                "SELECT * FROM completed WHERE id=?", (thread_id,)
            ).fetchone()
            if completed:
                if completed["proposal_hash"] != digest(proposal):
                    raise PolicyError("Completion is bound to a different proposal")
                return {**json.loads(completed["result"]), "already_completed": True}
            key = thread_id + ":" + digest(proposal)
            self.audit(
                thread_id,
                "delivery.started",
                {
                    "operation_key": key,
                    "proposal_hash": digest(proposal),
                    "provider": "local simulator",
                },
            )
            result = self.sink.reply(key, proposal)
            if crash_after_effect:
                os._exit(
                    86
                )  # Fault-injection only: remote DB committed; control DB not.
            self.control.execute(
                "INSERT INTO completed VALUES(?,?,?)",
                (thread_id, digest(proposal), canonical(result)),
            )
            self.audit(
                thread_id, "delivery.completed", {**result, "operation_key": key}
            )
            return result


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Governed support workflow; delivery is always a local simulator"
    )
    parser.add_argument("--data", default=".support-data")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Explicit fixture planner; no model or database credentials needed",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("thread")
    submit.add_argument("--ticket", required=True)
    submit.add_argument("--subject", required=True)
    submit.add_argument("--description", required=True)
    for name in ("inspect", "resume", "review", "deliver"):
        cmd = sub.add_parser(name)
        cmd.add_argument("thread")
        if name == "review":
            cmd.add_argument("--actor", required=True)
            cmd.add_argument("--team", required=True)
            cmd.add_argument(
                "--role", required=True, choices=["reviewer", "contributor"]
            )
            cmd.add_argument("--hash", required=True)
            cmd.add_argument(
                "--decision", default="approve", choices=["approve", "reject"]
            )
        if name == "deliver":
            cmd.add_argument(
                "--crash-after-effect",
                action="store_true",
                help="Test-only: exit process after simulator commits",
            )
    args = parser.parse_args()
    try:
        with Runtime(args.data, demo=args.demo) as runtime:
            if args.command == "submit":
                result = runtime.submit(
                    args.thread,
                    {
                        "ticket_id": args.ticket,
                        "subject": args.subject,
                        "description": args.description,
                    },
                )
            elif args.command == "review":
                result = runtime.review(
                    args.thread,
                    {"id": args.actor, "team": args.team, "role": args.role},
                    args.hash,
                    args.decision,
                )
            elif args.command == "deliver":
                result = runtime.deliver(args.thread, args.crash_after_effect)
            else:
                result = getattr(runtime, args.command)(args.thread)
        print(json.dumps(result, indent=2, default=str))
    except (PolicyError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
