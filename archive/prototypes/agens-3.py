from typing import TypedDict, List, Any, Dict

from dotenv import load_dotenv
from cpp_tool import CppSubprocessTool
from langchain_openai import ChatOpenAI
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_experimental.tools import PythonREPLTool

from langgraph.graph import StateGraph, END
from IPython.display import Image, display

import os
import json
import uuid
import datetime

from ns3_tool import Ns3Tool
from search_knowledge_base_tool_backup import create_search_knowledge_base_tool
from initialize_knowledge_base import initialize_knowledge_base
from read_example_tool import read_ns3_example, list_ns3_examples

from pydantic import BaseModel, Field
from langchain.agents import create_agent

from pydantic import BaseModel
from openai import OpenAI

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
gpt_model="gpt-5-mini"

llm = ChatOpenAI(model=gpt_model, temperature=0)


# Initialize collection once
knowledge_base_collection = initialize_knowledge_base()

cpp_tool = CppSubprocessTool(allow_dangerous_code=True)
search_tool = DuckDuckGoSearchRun()
python_repl_tool = PythonREPLTool()
search_knowledge_base_tool = create_search_knowledge_base_tool(knowledge_base_collection)

client = OpenAI()

class Custodian(BaseModel):
    thought: str = Field(description="Reasoning about what to search or read next")
    next_action: str = Field(description="search_knowledge_base|read_ns3_example|list_ns3_examples|null")
    action_input: str = Field(description="Detailed input for the tool (or null if finish=true)")
    summary: str = Field(description="Concise summary of gathered information so far")
    confident: bool = Field(description="Set to true when you have enough information to report back")
    final_report: str = Field(default=None, description="Detailed report of relevant gathered information (include only when confident is true)")

class CoderInput(BaseModel):
    code: str = Field(description="The full C++ code for the ns-3 simulation")
    language: str = Field(description="The programming language, usually 'cpp'")

class Coder(BaseModel):
    tool: str = Field(description="ns3_tool")
    tool_input: CoderInput = Field(description="Input for the ns3_tool")

class Evaluator(BaseModel):
    code_review: str = Field(description="Detailed code review focusing on correctness, efficiency, and adherence to best practices")
    evaluation: str = Field(description="Output of the terminal after running the code")

class ManagerResponse(BaseModel):
    thought: str = Field(description="Your reasoning")
    assistant: str = Field(description="Custodian|Coder|Evaluator|Null (if finish=true)")
    tool_input: str = Field(description="Detailed instructions for the assistant (or null if finish=true)")
    finish: bool = Field(description="true/false")

tools = {
    "search": search_tool, 
    "python_repl": python_repl_tool, 
    "ns3_tool": Ns3Tool, 
    "search_knowledge_base": search_knowledge_base_tool,
    "read_ns3_example": read_ns3_example,        
    "list_ns3_examples": list_ns3_examples       
}


class AgentState(TypedDict, total=False):
    question: str
    thoughts: List[str]
    actions: List[Dict[str, Any]]
    observations: List[str]
    final_answer: str
    iteration: int
    custodian_input: str
    custodian_output: str
    custodian_confident: bool
    coder_output: Dict[str, str]
    evaluator_output: Dict[str, str]
    current_assistant: str
    custodian_iteration: int
    visited_nodes: List[str]

CUSTODIAN_SYSTEM_PROMPT = """You are the Repository Custodian, a RAG specialist for gathering ns-3 documentation and example codes.
Your ONLY role is to find and retrieve correct information related to your manager's request. 

If you have enough information at your context without searching more, you MUST stop searching, set 'confident' to true and provide a detailed 'final_report'.

You will be provided with a task from your Manager, previous information you have gathered from documents so far.

You MUST write a "summary" for the collected information's very brief information so far in each response.

You MUST write down relevant code snippets from the examples you read. 
Do NOT just say "this example is good" or "refer to example X". 
You MUST extract and show the actual code lines that are relevant.
Explain how the code snippet helps solve the user's problem.

In your final report, Do not include questions or follow-up statements.

IMPORTANT: You have a limited number of search attempts. 
- If "search_knowledge_base" is not yielding useful results after 2-3 tries, STOP using it.
- Instead, switch to "list_ns3_examples" and "read_ns3_example" to find relevant code patterns.
- If you are running out of attempts, prioritize synthesizing what you have into a 'final_report' rather than making one last search.
- Do not get stuck in a loop searching for the same thing.

You have access to following tools to gather information:

1. "search_knowledge_base" - Search ns-3 documentation for facts and API references
   Input: search keywords string

2. "list_ns3_examples" - List available examples for a module (USE IF WARNING TRIGGERED)
   Input: keywords to find relevant example files
   Tip: After listing examples, use read_ns3_example to read the code of interest.

3. "read_ns3_example" - Read actual working ns-3 example code (USE IF WARNING TRIGGERED)
   Input: example name without .cc (e.g., "lena-x2-handover")
   

"""

CODER_SYSTEM_PROMPT = """You are the Coder Assistant, an expert ns-3 network simulator coder. 
Your Manager provides you with detailed simulation guidelines to implement alongside with any relevant documentation or example code. 
Your ONLY role is to write ns-3 simulation code.

You will use the ns3_tool to compile and run your simulation:

1. "ns3_tool" - Compile and run ns-3 simulation
   Input: {"code": "<full_cpp_code>", "language": "cpp"}
    - IMPORTANT: When creating ns-3 simulation code, make sure to include logging with "NS_LOG_COMPONENT_DEFINE("ns3Agent");"
    - If you are referencing an example you found using read_ns3_example, make sure to adapt it fully to your needs and change NS_LOG component name to "ns3Agent".
    - IMPORTANT: At the end of the simulation PRINT the following metrics to std::cout for all flows: 
        1) Total Packet Loss
        2) Average Delay (ms)
        3) Average Throughput (Mbps).
"""

EVALUATOR_SYSTEM_PROMPT = """You are an Evaluator Assistant, an expert ns-3 network code evaluator. 

Your Manager provides you with detailed simulation tasks to implement alongside with any relevant documentation or example code. 

Your ONLY role is to examine the ns-3 simulation code and it's outputs and determine if the code meets the simulation requirements.

In your final report, Do not include questions or follow-up statements.

"""

MANAGER_SYSTEM_PROMPT = """You are an expert ns-3 network simulator agent manager that reasons step-by-step planning to solve tasks.

You should choose your assistants based on the task requirements:

1. Custodian Assistant: Focuses on retrieving accurate ns-3 documentation and example codes.
   Input: Detailed instructions on what to search and report for.
   IMPORTANT: If you need code examples, emphasize that in your instructions.
   IMPORTANT: Do not add more than 2 requests to search, and rather split your task into multiple iterations if needed.
   Output: Concise summary with relevant information from ns-3 knowledge base.

2. Coder Assistant: Focuses on writing, debugging, and running ns-3 simulation code.
    Input: Detailed explanation of the simulation task to implement (with any relevant info from Custodian, such as syntax or examples).
    Output: Working ns-3 simulation code and execution results.
    IMPORTANT: Include fixes that address previous errors made by Coder Assistant if any. 

3. Evaluator Assistant: Focuses on reviewing code and determining if requirements are met.
    Input: The code, outputs, and original requirements.
    Output: Code review and success/failure evaluation.

Guidelines:
1. Start with Custodian if you need ns-3 documentation or examples.
2. Use Coder to implement simulations with context from Custodian if available.
3. Use Evaluator to check if the simulation meets requirements.
4. If evaluation fails, return to Custodian for alternative approaches or back to Coder for fixes.
5. When evaluation succeeds, set finish to true.
"""

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
        actions.append({
            "assistant": None,
            "tool_input": None,
            "finish": True,
        })
        return {
            **state,
            "thoughts": thoughts,
            "actions": actions,
            "iteration": iteration,
            "visited_nodes": visited_nodes,
        }
    
    history_str = ""
    for i, t in enumerate(thoughts):
        history_str += f"Thought {i+1}: {t}\n"
    
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

    print (f"\n[Manager] Invoking with message:\n{user_msg}\n")

    resp = client.responses.parse(
        model = gpt_model,
        input = [
            {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],        
        text_format=ManagerResponse
    )

    # response = manager_runnable.invoke(
    #     [
    #         {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
    #         {"role": "user", "content": user_msg},
    #     ])

    response = resp.output_parsed

    thoughts.append(response.thought)
    actions = state.get("actions", [])
    actions.append(
        {
            "assistant": response.assistant,
            "tool_input": response.tool_input,
            "finish": response.finish,
        }
    )

    state['custodian_input'] = response.tool_input if response.assistant == "Custodian" else ""
    
    # Reset custodian iteration count when manager assigns a new task
    if response.assistant == "Custodian":
        state['custodian_iteration'] = 0

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
        recent_obs = "\n".join(observations[-MAX_CUSTODIAN_ITER:]) if observations else "No observations yet."

        print(f"\n[Custodian] Reached maximum iterations ({MAX_CUSTODIAN_ITER}). Forcing confidence.")
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
        recent_obs = "\n".join(observations[-current_iter:]) if observations else "No observations yet."
        
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

    print (f"\n[Custodian] Invoking with message:\n{user_msg}\n")

    resp = client.responses.parse(
        model = gpt_model,
        input = [
            {"role": "system", "content": CUSTODIAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],        
        text_format=Custodian
    )

    response = resp.output_parsed
    
    # If forced to finish, ensure confident is true
    if current_iter >= MAX_CUSTODIAN_ITER:
        response.confident = True
        if not response.final_report:
            response.final_report = response.summary or "Terminated due to iteration limit. See summary."

    print(f"[Custodian] Response: {response}\n\n")
    
    print(f"\n[Custodian] Tool: {response.next_action}, Confident: {response.confident}")
    
    # Update actions with custodian's tool choice
    actions.append({
        "tool": response.next_action,
        "tool_input": response.action_input,
        "assistant": "Custodian",
    })
    
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

    print (f"\n[Coder] Invoking with message:\n{user_msg}\n")
    resp = client.responses.parse(
        model = gpt_model,
        input = [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],        
        text_format=Coder
    )
    response = resp.output_parsed

    print(f"\n[Coder] Generated code, preparing to execute")
    
    # Update actions with coder's tool choice
    # Convert Pydantic model to dict for tool execution
    tool_input_dict = response.tool_input.model_dump() if hasattr(response.tool_input, "model_dump") else response.tool_input.dict()

    actions.append({
        "tool": response.tool,
        "tool_input": tool_input_dict,
        "assistant": "Coder",
    })
    
    print(f"\n[Coder] Tool Input Code Snippet:\n{tool_input_dict}...\n")

    state['coder_output'] = tool_input_dict['code']

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

    if tool_name is None or tool_name == "null":
        observation = "No tool called."
    else:
        tool = tools.get(tool_name)
        if tool is None:
            observation = f"Tool {tool_name} not found."
        else:
            # Simple sync tool call
            observation = tool.run(tool_input)
            

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
    code_result= observations[-1]
        
    user_msg = (
        f"Original Task: {state['question']}\n\n"
        f"Generated Code: {state.get('coder_output', 'No code available')}\n\n"
        f"Simulation Output: {code_result}\n\n"
        "Evaluate if the simulation meets the requirements. Return JSON with 'code_review' and 'evaluation' fields."
    )

    print (f"\n[Evaluator] Invoking with message:\n{user_msg}\n")
    resp = client.responses.parse(
        model = gpt_model,
        input = [
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],        
        text_format=Evaluator
    )
    response = resp.output_parsed
    
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
    

    
FINAL_SYSTEM_PROMPT = """Provide a clear, concise final answer based on the reasoning steps and observations.
Focus on the results and insights. Avoid mentioning internal tools or thought processes unless relevant to the answer.
IMPORTANT: If the user question involved running ns-3 simulations, ensure to include the key metrics obtained from the simulation results in your final answer. The user is more interested in the numerical outcomes (e.g., throughput, delay, packet loss) than the code itself."""

def final_answer_node(state: AgentState) -> AgentState:
    visited_nodes = state.get("visited_nodes", [])
    visited_nodes.append("final")

    thoughts_str = "\n".join(
        f"Thought {i+1}: {t}" for i, t in enumerate(state.get("thoughts", []))
    )
    obs_str = "\n".join(
        f"Observation {i+1}: {o}" for i, o in enumerate(state.get("observations", []))
    )

    user_msg = (
        f"User question: {state['question']}\n\n"
        f"Your reasoning steps:\n{thoughts_str}\n\n"
        f"Tool results:\n{obs_str}\n\n"
        "Now give a helpful final answer to the user."
    )

    resp = llm.invoke(
        [
            {"role": "system", "content": FINAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    )

    return {
        **state,
        "final_answer": resp.content,
        "visited_nodes": visited_nodes,
    }

from langgraph.graph import StateGraph, END

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
    }
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
    }
)

# Evaluator returns to manager
graph.add_edge("evaluator", "manager")

# Final goes to END
graph.add_edge("final", END)

app = graph.compile()
mermaid_image = app.get_graph().draw_mermaid_png()

if __name__ == "__main__":

    question = "Use your tools to run a C++ code to calculate the factorial of 3 and give the result."
    
    question = """
Write an ns-3 simulation script for a High-Density Wi-Fi 6 (802.11ax) scenario. Create a network with 1 Access Point (AP) and N Stations (STAs). The number of stations (nWifi) must be defined as a Command-Line Argument with a default value of 10. To match my benchmark environment, you must explicitly configure the HE (High Efficiency) PHY settings:

- Channel Width: 40 MHz.
- Guard Interval: 800ns (0.8us).

Do not use UDP Echo. Use OnOffApplication on all stations sending data to the AP. 
Configure it in 'Constant' mode (DataRate: 100Mbps, PacketSize: 1024) to fully saturate the channel. 
Implement a logging mechanism (e.g., using Config::Connect) to log the instantaneous throughput (Mbps) every 100ms to a file named wifi_throughput.dat. 

Avoid using FlowMonitor; use manual tracing.
"""

    result = app.invoke(
        {
            "question": question,
            "thoughts": [],
            "actions": [],
            "observations": [],
            "iteration": 0,
            "visited_nodes": [],
        },
        config={"recursion_limit": 100}
    )

    # Save workflow log to JSON
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "question": question,
        "final_answer": result.get("final_answer"),
        "thoughts": result.get("thoughts"),
        "actions": result.get("actions"),
        "observations": result.get("observations"),
        "visited_nodes": result.get("visited_nodes"),
        "custodian_output": result.get("custodian_output"),
        "coder_output": result.get("coder_output"),
        "evaluator_output": result.get("evaluator_output"),
    }
    
    save_dir = "./saves/"
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    filename = f"{save_dir}workflow_log_{uuid.uuid4()}.json"
    with open(filename, "w") as f:
        json.dump(log_data, f, indent=4)
    
    print(f"\nWorkflow log saved to {filename}")

    print("=== FINAL ANSWER ===")
    print(result["final_answer"])
    # print("\n=== THOUGHTS ===")
    # for i, t in enumerate(result["thoughts"]):
    #    print(f"{i+1}. {t}")
    # print("\n=== ACTIONS ===")
    # for i, a in enumerate(result["actions"]):
    #    print(f"{i+1}. {a}")
    # print("\n=== OBSERVATIONS ===")
    # for i, o in enumerate(result["observations"]):
    #    print(f"{i+1}. {o}")