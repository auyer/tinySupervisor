import pytest

from tinysupervisor.errors import CyclicDependencyError, UnknownDependencyError
from tinysupervisor.graph import DependencyGraph


def test_topological_order():
    graph = DependencyGraph(["a", "b", "c"], {"b": ["a"], "c": ["b"]})
    assert graph.topological_order() == ["a", "b", "c"]


def test_topological_order_independent():
    graph = DependencyGraph(["a", "b"], {})
    assert set(graph.topological_order()) == {"a", "b"}


def test_predecessors():
    graph = DependencyGraph(["a", "b", "c"], {"b": ["a"], "c": ["a", "b"]})
    assert set(graph.predecessors("c")) == {"a", "b"}


def test_cycle_detection():
    with pytest.raises(CyclicDependencyError):
        DependencyGraph(["a", "b"], {"a": ["b"], "b": ["a"]})


def test_self_cycle():
    with pytest.raises(CyclicDependencyError):
        DependencyGraph(["a"], {"a": ["a"]})


def test_unknown_dependency():
    with pytest.raises(UnknownDependencyError):
        DependencyGraph(["a"], {"a": ["does_not_exist"]})
