from athena.core.handler import ExecutionContext, HandlerResult

NODE_REGISTRY: dict[str, object] = {}


def register(node_type: str):
    def deco(cls):
        if node_type in NODE_REGISTRY:
            raise ValueError(f"Duplicate node type: {node_type}")
        NODE_REGISTRY[node_type] = cls()
        return cls
    return deco


def get_handler(node_type: str):
    if node_type not in NODE_REGISTRY:
        raise KeyError(f"Unknown node type: {node_type!r}")
    return NODE_REGISTRY[node_type]
