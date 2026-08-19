import os
import sys

from tinysupervisor import CronJob, Job, RecurrentJob, init_supervisor


def main() -> int:
    supervisor = init_supervisor(
        verbosity=os.environ.get("TINYSUPERVISOR_VERBOSITY", "info")
    )
    # define task dependency each register task should depend on the previous,
    # they should only need them to start, not complete
    supervisor.auto_dependency_mode(mode="register_order", wait_for="start")

    started_job = Job(name="started_job", command='echo "started"')
    supervisor.register(started_job)
    supervisor.register(
        CronJob(
            name="heart_beat",
            interval=os.environ.get("TINYSUPERVISOR_CRON_INTERVAL", "2s"),
            run_until=os.environ.get("TINYSUPERVISOR_CRON_RUN_UNTIL", "10s"),
            command='echo "still running"',
            depends=["started_job"],
            wait_for="completed",  # run after the dependency is completed
        )
    )
    supervisor.register(
        RecurrentJob(
            name="confirmation",
            command='echo "beat confirmed"',
            depends=["heart_beat"],  # run every time the CronJob executes
        )
    )

    supervisor.register(
        Job(
            name="done",
            command='echo "done"',
            depends=["heart_beat"],
            wait_for="completed",  # only run after state is "completed"
        )
    )

    supervisor.set_heartbeat_interval("1m")  # default reconciler interval

    supervisor.set_http_port(int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081")))

    return supervisor.start()


if __name__ == "__main__":
    sys.exit(main())
