# TinySupervisor

Define workflows in Python, run anything you want.
Tiny to fit in a container, but with observability built in.

A Python library inspired by Supervisor and workflow APIs like Airflow.
It aims to be a simple way to define workflows to be easily included into a single container.

## Features

- **Task types**: Job (one-shot), CronJob (recurring), Service (long-running)
- **DAG dependencies**: `start`, `completed`, `run_after` modes
- **Built-in observability**: `/health`, `/state`, `/metrics` HTTP endpoints
- **Zero config**: single container friendly

## Install

Requires Python 3.14+.

(soon, not published yet)
```bash
uv add tinysupervisor
# or
pip install tinysupervisor
```

## Quick start

A minimal workflow with two jobs — the second waits for the first to complete:

```python
# runnable: quickstart
import os
import sys

from tinysupervisor import Job, init_supervisor


def main() -> int:
    supervisor = init_supervisor()
    supervisor.set_http_port(int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081")))
    supervisor.set_heartbeat_interval("100ms")

    supervisor.register(Job(name="prepare", command="echo preparing"))
    supervisor.register(
        Job(
            name="build",
            command="echo building",
            depends=["prepare"],
            dependency_mode="completed",
        )
    )

    return supervisor.start()


if __name__ == "__main__":
    sys.exit(main())
```

The supervisor starts an HTTP server (default port 8081), runs the tasks in dependency order, and **exits automatically** once all tasks complete:

- `prepare` runs first
- `build` waits for `prepare` to complete, then runs
- The supervisor exits with code `0` (or `1` if any task ends FATAL)

## Tasks

### Job

A one-shot task that runs once and completes (or fails):

```python
from tinysupervisor import Job

Job(name="backup", command="tar -czf backup.tar.gz /data")
```

Jobs can also run a Python function via `executable`:

```python
Job(name="greet", executable=lambda: print("hello"))
```

### CronJob

A task that runs on a recurring interval, optionally bounded by `run_until`:

```python
# runnable: cron
import os
import sys

from tinysupervisor import Job, CronJob, init_supervisor


def main() -> int:
    supervisor = init_supervisor()
    supervisor.set_http_port(int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081")))
    supervisor.set_heartbeat_interval("100ms")

    supervisor.register(Job(name="init", command="echo init"))
    supervisor.register(
        CronJob(
            name="heartbeat",
            interval="1s",
            run_until=3,
            command="echo beat",
            depends=["init"],
            dependency_mode="completed",
        )
    )

    return supervisor.start()


if __name__ == "__main__":
    sys.exit(main())
```

`run_until` can be an integer (max number of runs) or a duration string like `"30s"`.

### Service

A long-running task that the supervisor keeps alive until stopped:

```python
Service(name="server", command="python3 -m http.server 8080")
```

Services stay running until the supervisor receives `SIGINT` or `SIGTERM`.
When a service exits unexpectedly the supervisor can optionally restart it
(`autorestart=True`).

## Dependencies

Tasks can depend on others. The `dependency_mode` controls *when* the dependent task starts:

| Mode | Meaning |
|---|---|
| `start` | Start as soon as the dependency has started |
| `completed` | Wait until the dependency completes |
| `run_after` | Run every time the dependency runs |

```python
# runnable: run_after
import os
import sys

from tinysupervisor import Job, CronJob, init_supervisor


def main() -> int:
    supervisor = init_supervisor()
    supervisor.set_http_port(int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081")))
    supervisor.set_heartbeat_interval("100ms")

    supervisor.register(Job(name="seed", command="echo seed"))
    supervisor.register(
        CronJob(
            name="tick",
            interval="1s",
            run_until=2,
            command="echo tick",
            depends=["seed"],
            dependency_mode="completed",
        )
    )
    supervisor.register(
        Job(
            name="after_tick",
            command="echo after tick",
            depends=["tick"],
            dependency_mode="run_after",
        )
    )

    return supervisor.start()


if __name__ == "__main__":
    sys.exit(main())
```

You can also chain tasks automatically with `auto_dependency_mode`:

```python
supervisor.auto_dependency_mode(mode="register_order", wait_for="start")
# Each task registered after this call depends on the previous one (start mode).
```

## Observability

The supervisor exposes an HTTP server with three endpoints:

```bash
curl http://localhost:8081/health   # 200 OK or 400 Unhealthy
curl http://localhost:8081/state    # full JSON state of all tasks
curl http://localhost:8081/metrics  # Prometheus metrics
```

The `/state` endpoint returns JSON with each task's `current` state, `desired` state,
`run_count`, and `completed` flag, plus the dependency graph:

```json
{
  "processes": {
    "prepare": {"current": "completed", "desired": "completed", "run_count": 1, "completed": true},
    "build":   {"current": "completed", "desired": "completed", "run_count": 1, "completed": true}
  },
  "graph": {
    "nodes": ["prepare", "build"],
    "edges": [{"from": "prepare", "to": "build", "mode": "completed"}]
  }
}
```

## Exit codes

The supervisor's `start()` returns an exit code:

- **0** — all tasks completed successfully
- **1** — at least one task ended in `FATAL`

By default the supervisor **exits automatically** when all tasks reach a terminal
state (`COMPLETED` or `FATAL`). To keep it running (e.g. for long-running services), pass `keep_running=True`:

```python
supervisor = init_supervisor(keep_running=True)
```

## Verbosity

Control log output via the `Verbosity` enum or the `TINYSUPERVISOR_VERBOSITY`
environment variable:

| Level | Behaviour |
|---|---|
| `silent` | no output |
| `info` | task start and finish (default) |
| `debug` | every state transition |

```python
from tinysupervisor import Verbosity

supervisor = init_supervisor(verbosity=Verbosity.DEBUG)
```

## More examples

See the [`examples/`](examples/) directory for complete runnable scripts:

- `simple_dag.py` — cron heartbeat with downstream jobs
- `simple_server.py` — file-generation cron + HTTP server

## Process states

Tasks transition through these states during their lifecycle:

```
[starting] <-> [backoff]
 |   |  | \        v
 |   |  |  \___[FATAL]
 |   |  |
 |   | [EXITED]
 |   v   /\
 |  [running] <--> [waiting]
 |
  \> [stopping] -> [COMPLETED]
```

For full details see [`docs/DOCS.md`](docs/DOCS.md).
