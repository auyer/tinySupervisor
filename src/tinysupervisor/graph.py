"""Dependency graph built on top of tawazi's DAG machinery."""

from collections.abc import Mapping, Sequence

from networkx import NetworkXUnfeasible
from tawazi import DAG
from tawazi._helpers import StrictDict
from tawazi.node import ExecNode, UsageExecNode

from tinysupervisor.errors import CyclicDependencyError, UnknownDependencyError


class DependencyGraph:
    """A directed acyclic graph of task names and their dependencies.

    Backed by tawazi's ``DAG``/``ExecNode`` primitives, which give us cycle
    detection and topological ordering.
    """

    def __init__(
        self,
        names: Sequence[str],
        depends: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self._names = list(names)
        self._depends: dict[str, list[str]] = {
            name: list(depends.get(name, [])) if depends else [] for name in self._names
        }

        known = set(self._names)
        for name, deps in self._depends.items():
            for dep in deps:
                if dep not in known:
                    raise UnknownDependencyError(
                        f"task {name!r} depends on unknown task {dep!r}"
                    )

        self._dag = self._build_dag()

    def _build_dag(self) -> DAG:
        exec_nodes: dict[str, ExecNode] = {}
        for name in self._names:
            args = [UsageExecNode(dep) for dep in self._depends[name]]
            exec_nodes[name] = ExecNode(id_=name, args=args)
        try:
            return DAG(
                qualname="supervisor",
                results=StrictDict(),
                exec_nodes=StrictDict(exec_nodes),
                input_uxns=[],
                return_uxns=(),
                max_concurrency=1,
            )
        except NetworkXUnfeasible as exc:
            raise CyclicDependencyError(
                "the dependency graph contains a cycle"
            ) from exc

    def topological_order(self) -> list[str]:
        """Return task names in dependency-first topological order."""
        return list(self._dag.graph_ids.topologically_sorted)

    def predecessors(self, name: str) -> list[str]:
        """Return the direct dependencies of ``name``."""
        return list(self._dag.graph_ids.predecessors(name))
