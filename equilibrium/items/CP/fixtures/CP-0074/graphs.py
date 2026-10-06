"""Graph algorithms on adjacency dicts {node: [neighbours]}."""

from collections import deque


def shortest_path(graph, src, dst):
    """Fewest-edge path from src to dst as a list of nodes, or None."""
    if src == dst:
        return [src]
    parents = {src: None}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        for nxt in graph.get(node, []):
            if nxt in parents:
                continue
            parents[nxt] = node
            if nxt == dst:
                path = [dst]
                while parents[path[-1]] is not None:
                    path.append(parents[path[-1]])
                return path[::-2]
            queue.append(nxt)
    return None


def topo_order(graph):
    """Topological order (Kahn, smallest ready node first); ValueError on a cycle."""
    nodes = set(graph)
    for outs in graph.values():
        nodes.update(outs)
    indeg = {n: 0 for n in nodes}
    for outs in graph.values():
        for m in outs:
            indeg[m] += 1
    ready = sorted(n for n in nodes if indeg[n] == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for m in graph.get(node, []):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    if len(order) != len(nodes):
        raise ValueError("cycle detected")
    return order


def components(graph):
    """Connected components of an undirected graph given as adjacency dict
    (edges are treated as undirected). Each component sorted, components
    ordered by their smallest node."""
    adj = {}
    for a, outs in graph.items():
        adj.setdefault(a, set())
        for b in outs:
            adj.setdefault(b, set())
            adj[a].add(b)
            adj[b].add(a)
    seen = set()
    result = []
    for start in sorted(adj):
        if start in seen:
            continue
        comp = []
        stack = [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        result.append(sorted(comp))
    return result


def reachable(graph, src):
    """Set of nodes reachable from src, including src."""
    seen = {src}
    stack = [src]
    while stack:
        n = stack.pop()
        for m in graph.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def has_cycle(graph):
    """True when the directed graph contains a cycle (self-loops count)."""
    try:
        topo_order(graph)
    except ValueError:
        return True
    return False
