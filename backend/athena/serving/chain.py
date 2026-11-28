"""Build the preprocessing chain a deployed model replays on raw requests.

Walk upstream from the model's training input to the data source: splits mark the target to drop, nodes with a
replay step add it, training-only nodes (row filters, balancing) are skipped, and the first node that can't be
replayed (or that joins several inputs, except a merge replayed as a lookup on its left input) cuts the chain: requests then start from that node's output. The chain is
checked before it's used: replayed on the raw training rows it must reproduce the split's X_train exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from athena.core.artifacts import load_output, load_result
from athena.core.registry import NODE_META
from athena.schemas.pipeline import PipelineSpec
from athena.serving import replay_core

SPLITS = {"train_test", "train_val_test", "dataset_to_xy"}
DATA_PORTS = {"dataset", "X_train"}


@dataclass
class Chain:
    steps: list[dict[str, Any]]
    raw: pd.DataFrame              # what requests look like (the source's output, or the cut node's), target removed
    replayed: list[str] = field(default_factory=list)
    training_only: list[str] = field(default_factory=list)
    not_replayed: list[str] = field(default_factory=list)
    verified: bool = False
    note: str = ""


def _upstream_labels(spec: PipelineSpec, start: str) -> list[str]:
    out, frontier, seen = [], [start], {start}
    while frontier:
        nid = frontier.pop()
        meta = NODE_META.get(spec.node(nid).type)
        if meta and meta.inputs and meta.category in {"quality", "feature", "balance"}:
            out.append(meta.label)
        for e in spec.edges:
            if e.target == nid and e.source not in seen:
                seen.add(e.source)
                frontier.append(e.source)
    return sorted(set(out))


def _target_of(spec: PipelineSpec, run_id: str, split_id: str) -> str | None:
    from athena.utils.dataframes import get_target_column
    explicit = str(spec.node(split_id).config.get("target_col", "")).strip()
    if explicit:
        return explicit
    edge = next((e for e in spec.edges if e.target == split_id), None)
    if edge is None:
        return None
    frame = load_output(run_id, edge.source, edge.source_port)
    try:
        return str(get_target_column(frame))
    except Exception:  # noqa: BLE001 - no recognisable target: nothing to drop
        return None


def build_chain(spec: PipelineSpec, run_id: str, train_src: str, model_X: pd.DataFrame) -> Chain:
    steps: list[dict[str, Any]] = []
    replayed: list[str] = []
    training_only: list[str] = []
    target: str | None = None
    split_id: str | None = None
    cur = train_src
    cut: str | None = None
    while True:
        node = spec.node(cur)
        meta = NODE_META.get(node.type)
        if meta is None:
            cut = cur
            break
        if not meta.inputs:  # the data source: requests look like its output
            break
        incoming = [e for e in spec.edges if e.target == cur and e.target_port < len(meta.inputs)
                    and meta.inputs[e.target_port].type in DATA_PORTS]
        if node.type in SPLITS:
            split_id = split_id or cur
            target = target or _target_of(spec, run_id, cur)
        else:
            replay = getattr(load_result(run_id, cur), "replay", None)
            if replay is not None and "follow_port" in replay:  # a merge: requests come in on one side
                incoming = [e for e in incoming if e.target_port == replay["follow_port"]]
            if replay is None or len(incoming) != 1:
                cut = cur
                break
            label = f"{meta.label} ({replay['note']})" if replay.get("note") else meta.label
            (training_only if replay.get("kind") == "skip" else replayed).append(label)
            if replay.get("kind") != "skip":
                steps.append(replay)
        if len(incoming) != 1:
            cut = cur
            break
        cur = incoming[0].source

    steps.reverse()
    replayed.reverse()
    steps.append({"kind": "features", "columns": [str(c) for c in model_X.columns]})
    if cut is not None:  # requests start from the cut node's output; it and everything above it aren't replayed
        raw = model_X if spec.node(cut).type in SPLITS else load_output(run_id, cut, 0)
        not_replayed = _upstream_labels(spec, cut)
    else:
        raw = load_output(run_id, cur, 0)
        not_replayed = []
    raw = raw.drop(columns=[target]) if target and target in raw.columns else raw
    chain = Chain(steps, raw, replayed, training_only, sorted(set(not_replayed)))
    return verify(chain, spec, run_id, split_id, model_X)


def verify(chain: Chain, spec: PipelineSpec, run_id: str, split_id: str | None, model_X: pd.DataFrame) -> Chain:
    """Replay on the raw training rows; it must give the split's X_train exactly. Otherwise don't replay."""
    expected = load_output(run_id, split_id, 0) if split_id else model_X
    rows = expected.index.intersection(chain.raw.index)
    if len(rows) == 0 or len(rows) < len(expected):
        chain.note = "Couldn't line the training rows up with the raw data (an index was reset upstream), so the replay wasn't checked."
        return chain
    try:
        got = replay_core.apply(chain.steps, chain.raw.loc[rows])
        pd.testing.assert_frame_equal(got.reset_index(drop=True), expected.loc[rows].reset_index(drop=True),
                                      check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-12)
        chain.verified = True
    except (AssertionError, ValueError, KeyError, TypeError) as exc:
        # Don't ship preprocessing that doesn't reproduce training: fall back to model-ready features.
        chain.note = f"Replaying the preprocessing didn't reproduce the training features ({str(exc).splitlines()[0][:160]}), so it isn't included."
        chain.not_replayed = sorted(set(chain.not_replayed + chain.replayed))
        chain.replayed, chain.steps, chain.raw = [], [chain.steps[-1]], model_X
    return chain
