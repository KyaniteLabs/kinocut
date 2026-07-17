"""Render DAG step-count boundary contracts."""

import pytest

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_WORKFLOW_STEPS
from kinocut.render_dag import DAGNode, DAGOutput, DAGSource, RenderDAG


def _nodes(count: int) -> tuple[DAGNode, ...]:
    return tuple(
        DAGNode(
            id=f"n{index}",
            kind="trim",
            inputs={"src": "@sources.hero"},
            output="@outputs.out" if index == count - 1 else f"@work/n{index}",
        )
        for index in range(count)
    )


def test_step_count_at_cap_passes():
    dag = RenderDAG(
        sources={"hero": DAGSource(path="hero.mp4")},
        nodes=_nodes(MAX_WORKFLOW_STEPS),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    assert len(dag.nodes) == MAX_WORKFLOW_STEPS


def test_step_count_over_cap_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": DAGSource(path="hero.mp4")},
            nodes=_nodes(MAX_WORKFLOW_STEPS + 1),
            outputs={"out": DAGOutput(path="out.mp4")},
        )
