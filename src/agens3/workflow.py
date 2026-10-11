"""LangGraph orchestration, built explicitly without import-time API calls."""

from langgraph.graph import END, StateGraph
from openai import OpenAI

from .config import Settings
from .knowledge_base import initialize_knowledge_base
from .models import AgentState, Coder, Custodian, Evaluator, ManagerResponse
from .prompts import (
    CODER_SYSTEM_PROMPT,
    CUSTODIAN_SYSTEM_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
    FINAL_SYSTEM_PROMPT,
    MANAGER_SYSTEM_PROMPT,
)
from .tools.examples import create_example_tools
from .tools.knowledge_search import create_search_knowledge_base_tool
from .tools.simulator import create_simulator_tool


def create_workflow(settings: Settings | None = None, *, client=None, collection=None):
    """Build a workflow; injected clients and collections support offline testing."""
    settings = settings or Settings.from_env()
    if client is None:
        settings.require_api_key()
        client = OpenAI(api_key=settings.openai_api_key)
    if collection is None:
        collection = initialize_knowledge_base(settings)
    gpt_model = settings.openai_model
    read_ns3_example, list_ns3_examples = create_example_tools(settings)
    tools = {
        "ns3_tool": create_simulator_tool(settings),
        "search_knowledge_base": create_search_knowledge_base_tool(collection),
        "read_ns3_example": read_ns3_example,
        "list_ns3_examples": list_ns3_examples,
    }

    def manager_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("manager")

        thoughts = state.get("thoughts", [])
        iteration = state.get("iteration", 0) + 1

        # Max iteration safeguard
        MAX_ITERATIONS = 15
        if iteration > MAX_ITERATIONS:
            thoughts.append(f"Reached maximum iterations ({MAX_ITERATIONS}). Finishing.")
            actions = state.get("actions", [])
            actions.append(
                {
                    "assistant": None,
                    "tool_input": None,
                    "finish": True,
                }
            )
            return {
                **state,
                "thoughts": thoughts,
                "actions": actions,
                "iteration": iteration,
                "visited_nodes": visited_nodes,
            }

        history_str = ""
        for i, t in enumerate(thoughts):
            history_str += f"Thought {i + 1}: {t}\n"

        if state.get("custodian_output"):
            history_str += f"\nCustodian's Report: {state['custodian_output']}\n"
        if state.get("coder_output"):
            history_str += f"\nCoder's Result: {state['coder_output']}\n"
        if state.get("evaluator_output"):
            history_str += f"\nCode Output {state['evaluator_output'].get('evaluation', 'No evaluation')} \n Evaluator's Review: {state['evaluator_output'].get('code_review', 'No review')}\n"

        user_msg = (
            f"User question: {state['question']}\n\n"
            f"Previous steps:\n{history_str}\n"
            f"Iteration: {iteration}/{MAX_ITERATIONS}\n\n"
            "Decide which assistant to use next."
        )

        print(f"\n[Manager] Invoking with message:\n{user_msg}\n")

        resp = client.responses.parse(
            model=gpt_model,
            input=[
                {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            text_format=ManagerResponse,
        )

        # response = manager_runnable.invoke(
        #     [
        #         {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
        #         {"role": "user", "content": user_msg},
        #     ])

        response = resp.output_parsed
        if response is None:
            raise RuntimeError(
                "The model did not return a structured response; check for refusal or incomplete output."
            )

        thoughts.append(response.thought)
        actions = state.get("actions", [])
        actions.append(
            {
                "assistant": response.assistant,
                "tool_input": response.tool_input,
                "finish": response.finish,
            }
        )

        state["custodian_input"] = response.tool_input if response.assistant == "Custodian" else ""

        # Reset custodian iteration count when manager assigns a new task
        if response.assistant == "Custodian":
            state["custodian_iteration"] = 0

        print(f"\n[Manager] Thought: {response.thought}")
        print(f"[Manager] Next Assistant: {response.assistant}")

        return {
            **state,
            "thoughts": thoughts,
            "actions": actions,
            "iteration": iteration,
            "visited_nodes": visited_nodes,
        }

    def custodian_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("custodian")

        actions = state.get("actions", [])
        if not actions:
            return {**state, "visited_nodes": visited_nodes}

        # Check iteration limit
        current_iter = state.get("custodian_iteration", 0)
        MAX_CUSTODIAN_ITER = 6

        # Build context of what custodian has gathered so far
        gathered_info = state.get("custodian_output", "None yet.")

        # Check for repetitive tool usage
        recent_tools = [a.get("tool") for a in actions if a.get("assistant") == "Custodian"][-3:]
        kb_spam = len(recent_tools) >= 2 and all(t == "search_knowledge_base" for t in recent_tools)
        observations = state.get("observations", [])

        if current_iter >= MAX_CUSTODIAN_ITER:
            recent_obs = (
                "\n".join(observations[-MAX_CUSTODIAN_ITER:])
                if observations
                else "No observations yet."
            )

            print(
                f"\n[Custodian] Reached maximum iterations ({MAX_CUSTODIAN_ITER}). Forcing confidence."
            )
            # Force a final report generation without tool usage
            user_msg = (
                f"Task from Manager: {state.get('custodian_input', '')}\n\n"
                f"Information gathered so far: {gathered_info}\n\n"
                f"Your Findings: {recent_obs}\n\n"
                f"You have reached the maximum number of search attempts ({MAX_CUSTODIAN_ITER}).\n"
                "You MUST now provide a final report based on what you have found so far.\n"
                "Set 'confident' to true and provide the 'final_report'. Do not call any more tools."
            )
        else:
            observations = state.get("observations", [])
            recent_obs = (
                "\n".join(observations[-current_iter:])
                if observations and current_iter
                else "No observations yet."
            )

            warning_msg = ""
            if current_iter >= MAX_CUSTODIAN_ITER - 3:
                warning_msg += f"\nWARNING: You have only {MAX_CUSTODIAN_ITER - current_iter} attempts left. Prioritize summarizing or finding code examples now.\n"

            if kb_spam:
                warning_msg += "\nWARNING: You are using 'search_knowledge_base' repeatedly. Try 'list_ns3_examples' or 'read_ns3_example' to find code instead.\n"

            user_msg = (
                f"Task from Manager: {state.get('custodian_input', '')}\n\n"
                f"{warning_msg}"
                f"Information gathered so far: {gathered_info}\n\n"
                f"Recent documentation results: {recent_obs}\n\n"
                f"Search Iteration: {current_iter + 1}/{MAX_CUSTODIAN_ITER}\n"
            )

        print(f"\n[Custodian] Invoking with message:\n{user_msg}\n")

        resp = client.responses.parse(
            model=gpt_model,
            input=[
                {"role": "system", "content": CUSTODIAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            text_format=Custodian,
        )

        response = resp.output_parsed
        if response is None:
            raise RuntimeError(
                "The model did not return a structured response; check for refusal or incomplete output."
            )

        # If forced to finish, ensure confident is true
        if current_iter >= MAX_CUSTODIAN_ITER:
            response.confident = True
            if not response.final_report:
                response.final_report = (
                    response.summary or "Terminated due to iteration limit. See summary."
                )

        print(f"[Custodian] Response: {response}\n\n")

        print(f"\n[Custodian] Tool: {response.next_action}, Confident: {response.confident}")

        # Update actions with custodian's tool choice
        actions.append(
            {
                "tool": response.next_action,
                "tool_input": response.action_input,
                "assistant": "Custodian",
            }
        )

        return {
            **state,
            "custodian_output": response.final_report if response.confident else response.summary,
            "custodian_confident": response.confident,
            "current_assistant": "Custodian",
            "actions": actions,
            "custodian_iteration": current_iter + 1,
            "visited_nodes": visited_nodes,
        }

    def coder_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("coder")

        actions = state.get("actions", [])
        if not actions:
            return {**state, "visited_nodes": visited_nodes}

        last_action = actions[-1]
        tool_input = last_action.get("tool_input")

        # Include custodian context if available
        context = ""
        if state.get("custodian_output"):
            context = f"\nRelevant Information/Examples for Coding:\n{state['custodian_output']}\n"

        user_msg = (
            f"User's Task: {state['question']}\n\n"
            f"Manager's Notes: {tool_input}{context}\n\n"
            f"Previous code to work on (if any): {state.get('coder_output', 'None')}\n\n"
            "Write the ns-3 simulation code."
        )

        print(f"\n[Coder] Invoking with message:\n{user_msg}\n")
        resp = client.responses.parse(
            model=gpt_model,
            input=[
                {"role": "system", "content": CODER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            text_format=Coder,
        )
        response = resp.output_parsed
        if response is None:
            raise RuntimeError(
                "The model did not return a structured response; check for refusal or incomplete output."
            )

        print("\n[Coder] Generated code, preparing to execute")

        # Update actions with coder's tool choice
        # Convert Pydantic model to dict for tool execution
        tool_input_dict = (
            response.tool_input.model_dump()
            if hasattr(response.tool_input, "model_dump")
            else response.tool_input.dict()
        )

        actions.append(
            {
                "tool": response.tool,
                "tool_input": tool_input_dict,
                "assistant": "Coder",
            }
        )

        print(f"\n[Coder] Tool Input Code Snippet:\n{tool_input_dict}...\n")

        state["coder_output"] = tool_input_dict["code"]
        state["coder_language"] = tool_input_dict["language"]

        return {
            **state,
            "current_assistant": "Coder",
            "actions": actions,
            "visited_nodes": visited_nodes,
        }

    def act_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("act")

        actions = state.get("actions", [])
        if not actions:
            return {**state, "visited_nodes": visited_nodes}

        last_action = actions[-1]
        tool_name = last_action.get("tool")
        tool_input = last_action.get("tool_input")

        observation = None

        if state.get("current_assistant") == "Custodian" and state.get("custodian_confident"):
            return state

        if tool_name is None or tool_name == "null":
            observation = "No tool called."
        else:
            tool = tools.get(tool_name)
            if tool is None:
                observation = f"Tool {tool_name} not found."
            else:
                # Simple sync tool call
                try:
                    observation = tool.run(tool_input)
                except Exception as exc:
                    observation = f"Tool {tool_name} failed: {exc}"

        observations = state.get("observations", [])
        observations.append(str(observation))

        print(f"Observation: {observation}\n|| END OF OBSERVATION ||\n")

        return {
            **state,
            "observations": observations,
            "visited_nodes": visited_nodes,
        }

    def evaluator_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("evaluator")

        observations = state.get("observations", [])
        code_result = observations[-1] if observations else "No simulation output available."

        user_msg = (
            f"Original Task: {state['question']}\n\n"
            f"Generated Code: {state.get('coder_output', 'No code available')}\n\n"
            f"Simulation Output: {code_result}\n\n"
            "Evaluate if the simulation meets the requirements. Return JSON with 'code_review' and 'evaluation' fields."
        )

        print(f"\n[Evaluator] Invoking with message:\n{user_msg}\n")
        resp = client.responses.parse(
            model=gpt_model,
            input=[
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            text_format=Evaluator,
        )
        response = resp.output_parsed
        if response is None:
            raise RuntimeError(
                "The model did not return a structured response; check for refusal or incomplete output."
            )

        print(f"\n[Evaluator] Evaluation: {response.evaluation[:500]}...")

        return {
            **state,
            "evaluator_output": response.model_dump(),
            "visited_nodes": visited_nodes,
        }

    def route_from_manager(state: AgentState) -> str:
        actions = state.get("actions", [])
        if not actions:
            return "final"

        last_action = actions[-1]
        if last_action.get("finish"):
            return "final"

        assistant = last_action.get("assistant")
        if assistant == "Custodian":
            return "custodian"
        elif assistant == "Coder":
            return "coder"
        elif assistant == "Evaluator":
            return "evaluator"
        else:
            return "final"

    def route_from_act(state: AgentState) -> str:
        """Route from act node based on current assistant"""
        current_assistant = state.get("current_assistant")

        if current_assistant == "Custodian":
            # Check if custodian is confident
            if state.get("custodian_confident"):
                return "manager"
            else:
                return "custodian"
        elif current_assistant == "Coder":
            return "evaluator"
        else:
            return "manager"

    def final_answer_node(state: AgentState) -> AgentState:
        visited_nodes = state.get("visited_nodes", [])
        visited_nodes.append("final")

        thoughts_str = "\n".join(
            f"Thought {i + 1}: {t}" for i, t in enumerate(state.get("thoughts", []))
        )
        obs_str = "\n".join(
            f"Observation {i + 1}: {o}" for i, o in enumerate(state.get("observations", []))
        )

        user_msg = (
            f"User question: {state['question']}\n\n"
            f"Your reasoning steps:\n{thoughts_str}\n\n"
            f"Tool results:\n{obs_str}\n\n"
            "Now give a helpful final answer to the user."
        )

        resp = client.responses.create(
            model=gpt_model,
            input=[
                {"role": "system", "content": FINAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )

        return {
            **state,
            "final_answer": resp.output_text,
            "visited_nodes": visited_nodes,
        }

    graph = StateGraph(AgentState)

    graph.add_node("manager", manager_node)
    graph.add_node("custodian", custodian_node)
    graph.add_node("coder", coder_node)
    graph.add_node("act", act_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("final", final_answer_node)

    # Entry point
    graph.set_entry_point("manager")

    # Manager routes to appropriate assistant or final
    graph.add_conditional_edges(
        "manager",
        route_from_manager,
        {
            "custodian": "custodian",
            "coder": "coder",
            "evaluator": "evaluator",
            "final": "final",
        },
    )

    # Both custodian and coder go to act node
    graph.add_edge("custodian", "act")
    graph.add_edge("coder", "act")

    # Act node routes based on current assistant:
    # - Custodian: back to custodian (loop) or manager (when confident)
    # - Coder: to evaluator
    graph.add_conditional_edges(
        "act",
        route_from_act,
        {
            "custodian": "custodian",
            "coder": "evaluator",
            "evaluator": "evaluator",
            "manager": "manager",
        },
    )

    # Evaluator returns to manager
    graph.add_edge("evaluator", "manager")

    # Final goes to END
    graph.add_edge("final", END)

    return graph.compile()
