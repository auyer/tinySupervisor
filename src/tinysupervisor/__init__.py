"""tinySupervisor: a process supervisor with DAG-like dependencies."""

from tinysupervisor.jobs import CronJob, Job, RecurrentJob
from tinysupervisor.logger import Verbosity
from tinysupervisor.process import Process
from tinysupervisor.service import Service
from tinysupervisor.states import DesiredState, ProcessState
from tinysupervisor.supervisor import Supervisor, init_supervisor

__all__ = [
    "CronJob",
    "DesiredState",
    "Job",
    "Process",
    "ProcessState",
    "RecurrentJob",
    "Service",
    "Supervisor",
    "Verbosity",
    "init_supervisor",
]

__version__ = "0.1.0"
