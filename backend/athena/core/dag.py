from collections import deque


def topo_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Kahn's algorithm. Raises ValueError if cycle detected."""
    node_ids = [n["id"] for n in nodes]
    in_deg: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}

    for e in edges:
        src, tgt = e["source"], e["target"]
        if tgt in in_deg:
            in_deg[tgt] += 1
        if src in adj:
            adj[src].append(tgt)

    queue: deque[str] = deque(nid for nid in node_ids if in_deg[nid] == 0)
    order: list[str] = []

    while queue:
        nid = queue.popleft()
        order.append(nid)
        for tgt in adj.get(nid, []):
            in_deg[tgt] -= 1
            if in_deg[tgt] == 0:
                queue.append(tgt)

    if len(order) != len(node_ids):
        raise ValueError("Pipeline contains a cycle")
    return order


def has_cycle(nodes: list[dict], edges: list[dict]) -> bool:
    try:
        topo_sort(nodes, edges)
        return False
    except ValueError:
        return True


def is_descendant_of(node_id: str, ancestors: list[str], edges: list[dict]) -> bool:
    """Returns True if node_id is reachable from any ancestor via edges."""
    reachable: set[str] = set()
    queue: deque[str] = deque(ancestors)
    while queue:
        cur = queue.popleft()
        for e in edges:
            if e["source"] == cur and e["target"] not in reachable:
                reachable.add(e["target"])
                queue.append(e["target"])
    return node_id in reachable
