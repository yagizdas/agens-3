from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agens3.models import Coder, CoderInput, Custodian, Evaluator, ManagerResponse
from agens3.workflow import create_workflow


def manager(role="Null", finish=False):
    return ManagerResponse(
        thought="next step", assistant=role, tool_input="scenario", finish=finish
    )


def fake_client(*responses):
    parsed = [SimpleNamespace(output_parsed=response) for response in responses]
    return SimpleNamespace(
        responses=SimpleNamespace(
            parse=Mock(side_effect=parsed),
            create=Mock(return_value=SimpleNamespace(output_text="report")),
        )
    )


def initial_state():
    return {
        "question": "scenario",
        "thoughts": [],
        "actions": [],
        "observations": [],
        "iteration": 0,
        "visited_nodes": [],
    }


def collection():
    result = Mock()
    result.count.return_value = 0
    return result


def test_manager_can_finish_without_tools(settings):
    client = fake_client(manager(finish=True))
    graph = create_workflow(settings, client=client, collection=collection())
    result = graph.invoke(initial_state())
    assert result["visited_nodes"] == ["manager", "final"]
    assert result["final_answer"] == "report"


def test_coder_runs_simulator_then_evaluator(settings, monkeypatch):
    import agens3.tools.simulator

    run = Mock(return_value="Exit code: 0\nReceived bytes: 100")
    monkeypatch.setattr(agens3.tools.simulator, "run_simulation", run)
    client = fake_client(
        manager("Coder"),
        Coder(tool="ns3_tool", tool_input=CoderInput(code="int main() {}", language="cpp")),
        Evaluator(code_review="meets requirements", evaluation="Received bytes: 100"),
        manager(finish=True),
    )
    result = create_workflow(settings, client=client, collection=collection()).invoke(
        initial_state()
    )
    assert result["visited_nodes"] == ["manager", "coder", "act", "evaluator", "manager", "final"]
    assert result["observations"] == ["Exit code: 0\nReceived bytes: 100"]
    assert result["coder_output"] == "int main() {}"
    run.assert_called_once_with("int main() {}", "cpp", settings)


def test_confident_custodian_does_not_call_retrieval(settings):
    db = collection()
    client = fake_client(
        manager("Custodian"),
        Custodian(
            thought="enough context",
            next_action="search_knowledge_base",
            action_input="wifi",
            summary="summary",
            confident=True,
            final_report="reference report",
        ),
        manager(finish=True),
    )
    result = create_workflow(settings, client=client, collection=db).invoke(initial_state())
    assert result["custodian_output"] == "reference report"
    assert result["observations"] == []
    db.count.assert_not_called()


def test_custodian_limit_forces_return_to_manager(settings):
    searching = Custodian(
        thought="search",
        next_action="search_knowledge_base",
        action_input="wifi",
        summary="partial",
        confident=False,
    )
    client = fake_client(
        manager("Custodian"), *[searching.model_copy() for _ in range(7)], manager(finish=True)
    )
    result = create_workflow(settings, client=client, collection=collection()).invoke(
        initial_state(), config={"recursion_limit": 50}
    )
    assert result["custodian_confident"] is True
    assert len(result["observations"]) == 6
    assert result["final_answer"] == "report"


def test_refusal_fails_with_clear_message(settings):
    graph = create_workflow(settings, client=fake_client(None), collection=collection())
    with pytest.raises(RuntimeError, match="structured response"):
        graph.invoke(initial_state())
