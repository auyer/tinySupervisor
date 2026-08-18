# TinySupervisor

# TODO: write acctual docs

## Processes

Job -> one time task
CronJob -> schedule a job to run acording to a cron expression, or interval
Service -> A long running task that is not expected to exit (like a web service).

## process dependencies:
Processes can depend on a process being COMPLETED or RUNNING.
A Processes can be scheduled to run after every execution of another task.



## Process states

Heavily inspired by Supervisor, with only a few changes.


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


A process controlled by tinySupervisor will be in one of the below states at any given time. You may see these state names in various user interface elements in clients.

COMPLETED (0)

    The process has been COMPLETED due to a stop request, and it stopped successfully.

STARTING (10)

    The process is starting due to a start request.

RUNNING (20)

    The process is running.

BACKOFF (30)

    The process entered the STARTING state but subsequently exited too quickly (before the time defined in startsecs) to move to the RUNNING state.

STOPPING (40)

    The process is stopping due to a stop request.

WAITING (50)

    The process is waiting for a condition to start running. It could be sleeping due to a configured interval, or for a dependency to be COMPLETED (or RUNNING)

EXITED (100)

    The process exited from the RUNNING state (expectedly or unexpectedly).

FATAL (200)

    The process could not be started successfully.

UNKNOWN (1000)

    The process is in an unknown state (tinySupervisor programming error).

Each process run under supervisor progresses through these states as per the following directed graph.
Subprocess State Transition Graph

Subprocess State Transition Graph

A process is in the COMPLETED state if it has been COMPLETED administratively or if it has never been started.

When an autorestarting process is in the BACKOFF state, it will be automatically restarted by tinySupervisor. It will switch between STARTING and BACKOFF states until it becomes evident that it cannot be started because the number of startretries has exceeded the maximum, at which point it will transition to the FATAL state.

Note

Retries will take increasingly more time depending on the number of subsequent attempts made, adding one second each time.

So if you set startretries=3, tinySupervisor will wait one, two and then three seconds between each restart attempt, for a total of 6 seconds.

When a process is in the EXITED state, it will automatically restart:

    never if its autorestart parameter is set to false.

    unconditionally if its autorestart parameter is set to true.

    conditionally if its autorestart parameter is set to unexpected. If it exited with an exit code that doesn’t match one of the exit codes defined in the exitcodes configuration parameter for the process, it will be restarted.

A process automatically transitions from EXITED to RUNNING as a result of being configured to autorestart conditionally or unconditionally. The number of transitions between RUNNING and EXITED is not limited in any way: it is possible to create a configuration that endlessly restarts an exited process. This is a feature, not a bug.

An autorestarted process will never be automatically restarted if it ends up in the FATAL state (it must be manually restarted from this state).

A process transitions into the STOPPING state via an administrative stop request, and will then end up in the COMPLETED state.

A process that cannot be COMPLETED successfully will stay in the STOPPING state forever. This situation should never be reached during normal operations as it implies that the process did not respond to a final SIGKILL signal sent to it.
