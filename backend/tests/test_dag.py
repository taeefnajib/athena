import pytest
from athena.core.dag import topo_sort, has_cycle, is_descendant_of


def test_topo_sort_chain():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    order = topo_sort(nodes, edges)
    assert order.index("a") < order.index("b")
    assert order.index("b") < order.index("c")


def test_topo_sort_raises_on_cycle():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    with pytest.raises(ValueError, match="cycle"):
        topo_sort(nodes, edges)


def test_has_cycle_false():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"source": "a", "target": "b"}]
    assert not has_cycle(nodes, edges)


def test_has_cycle_true():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    assert has_cycle(nodes, edges)


def test_is_descendant_of():
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    assert is_descendant_of("c", ["a"], edges)
    assert not is_descendant_of("a", ["c"], edges)
    assert is_descendant_of("b", ["a"], edges)
