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

from ns3_tool import Ns3Tool
from search_knowledge_base_tool_backup import create_search_knowledge_base_tool
from initialize_knowledge_base import initialize_knowledge_base
from read_example_tool import read_ns3_example, list_ns3_examples

from pydantic import BaseModel, Field
from langchain.agents import create_agent

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

llm = ChatOpenAI(model="gpt-5-mini", temperature=0)

gpt_model="gpt-5-mini"

# Initialize collection once
knowledge_base_collection = initialize_knowledge_base()

cpp_tool = CppSubprocessTool(allow_dangerous_code=True)
search_tool = DuckDuckGoSearchRun()
python_repl_tool = PythonREPLTool()
search_knowledge_base_tool = create_search_knowledge_base_tool(knowledge_base_collection)

class Custodian(BaseModel):
    thought: str = Field(description="Reasoning about what to search or read next")
    next_action: str = Field(description="search_knowledge_base|read_ns3_example|list_ns3_examples|null")
    action_input: str = Field(description="Detailed input for the tool (or null if finish=true)")
    summary: str = Field(description="Concise summary of gathered information so far")
    confident: bool = Field(description="Set to true when you have enough information to report back")
    final_report: str = Field(default=None, description="Detailed report of all gathered information (include only when confident is true)")

class Coder(BaseModel):
    code: str = Field(description="The full C++ code for the ns-3 simulation")
    language: str = Field(description="The programming language, usually 'cpp'")

class Evaluator(BaseModel):
    code_review: str = Field(description="Detailed code review focusing on correctness, efficiency, and adherence to best practices")
    evaluation: str = Field(description="Output of the terminal after running the code")
    success: bool = Field(description="True if the simulation compiled and ran successfully, False if there were errors")
    specific_errors: str = Field(default="", description="Specific compilation or runtime errors extracted from the output")

class ManagerResponse(BaseModel):
    thought: str = Field(description="Your reasoning")
    assistant: str = Field(description="Custodian|Coder|Evaluator")
    tool_input: str = Field(description="Detailed instructions for the assistant")
    finish: bool = Field(description="true/false")

custodian_agent = create_agent(
    model=gpt_model,
    response_format=Custodian
)

coder_agent = create_agent(
    model=gpt_model,
    response_format=Coder  
)
evaluator_agent = create_agent(
    model=gpt_model,
    response_format=Evaluator  
)
manager_agent = create_agent(
    model=gpt_model,
    response_format=ManagerResponse  
)
# Direct runnable for Custodian to avoid parsing issues
custodian_runnable = llm.with_structured_output(Custodian, method="function_calling")

coder_runnable = llm.with_structured_output(Coder, method="function_calling")

manager_runnable = llm.with_structured_output(ManagerResponse, method="function_calling")

evaluator_runnable = llm.with_structured_output(Evaluator, method="function_calling")  

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
    custodian_output: str
    custodian_confident: bool
    coder_output: Dict[str, str]
    coder_history: List[Dict[str, str]]  # NEW: Track all code attempts
    evaluator_output: Dict[str, str]
    current_assistant: str

CUSTODIAN_SYSTEM_PROMPT = """You are the Repository Custodian, a RAG specialist for gathering ns-3 documentation and example codes.
Your ONLY role is to find and retrieve correct information related to your manager's request. 

You can split your manager's request into parts and search for each part separately. You can call the same tools more than once until you are confident.

You MUST write down relevant code snippets from the examples you read. 
Do NOT just say "this example is good" or "refer to example X". 
You MUST extract and show the actual code lines that are relevant (e.g., how to configure a helper, how to set up a mobility model, etc.).
Explain WHY the code snippet is relevant and how it helps solve the user's problem.

You have access to following tools to gather information:

1. "search_knowledge_base" - Search ns-3 documentation for facts and API references
   Input: search keywords string

2. "read_ns3_example" - Read actual working ns-3 example code
   Input: example name without .cc (e.g., "lena-x2-handover")
   
3. "list_ns3_examples" - List available examples for a module
   Input: module name
   Tip: After listing examples, use read_ns3_example to read the code of interest.

CRITICAL RULES FOR SETTING confident=True:
1. Your final_report MUST contain ACTUAL C++ CODE SNIPPETS (not promises or descriptions)
2. Code snippets must be ALREADY RETRIEVED from tools (visible in "Recent tool results")
3. Each code snippet must include:
   - The actual C++ code lines
   - Explanation of what it does
   - Why it's relevant to the task
4. DO NOT set confident=True if you're planning to retrieve code "next" - you must HAVE it already
5. If you only have example names, you are NOT confident yet - use read_ns3_example first

If you say "Will include code snippets..." you are NOT confident. Only say confident=True when you HAVE the snippets. 

"""

CODER_SYSTEM_PROMPT = """You are the Coder Assistant, an expert ns-3 network simulator coder. 
Your Manager provides you with detailed simulation tasks to implement alongside with any relevant documentation or example code. 
Your ONLY role is to write ns-3 simulation code.

CRITICAL: If you are fixing a compilation error from a previous attempt:
1. Carefully read the EXACT error message provided
2. Identify the SPECIFIC line and issue
3. DO NOT repeat the same mistake
4. Apply the EXACT fix suggested in the error analysis
5. Review similar examples if the error relates to callback scheduling or function calls

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

CRITICAL: When analyzing compilation errors:
1. Extract the EXACT error message from the compiler output
2. Identify the SPECIFIC line number and problematic code
3. Explain WHY the error occurred
4. Provide the SPECIFIC fix needed (not just general advice)
5. Set 'success' to False if there are any compilation or runtime errors
6. In 'specific_errors' field, include:
   - The exact compiler error message
   - The line number
   - The specific code that needs to be changed
   - The exact replacement code
"""

MANAGER_SYSTEM_PROMPT = """You are an expert ns-3 network simulator agent manager that reasons step-by-step planning to solve tasks.

You should choose your assistants based on the task requirements:

1. Custodian Assistant: Focuses on retrieving accurate ns-3 documentation and example codes.
   Input: Detailed instructions on what to search and report for.
   Output: Concise summary with relevant information from ns-3 knowledge base.

2. Coder Assistant: Focuses on writing, debugging, and running ns-3 simulation code.
    Input: Detailed explanation of the simulation task to implement (with any relevant info from Custodian, such as syntax or examples).
    Output: Working ns-3 simulation code and execution results.

3. Evaluator Assistant: Focuses on reviewing code and determining if requirements are met.
    Input: The code, outputs, and original requirements.
    Output: Code review and success/failure evaluation.

Guidelines:
1. Start with Custodian if you need ns-3 documentation or examples.
2. Use Coder to implement simulations with context from Custodian if available.
3. Use Evaluator to check if the simulation meets requirements.
4. If evaluation fails, CRITICALLY:
   a. Extract the SPECIFIC error from evaluator's 'specific_errors' field
   b. Pass the COMPLETE error message to Coder
   c. Include what was tried before (previous code) so Coder doesn't repeat the mistake
   d. Reference the relevant documentation/examples for the fix
5. When evaluation succeeds (success=True), set finish to true.

CRITICAL: When passing instructions to Coder after a failed evaluation:
- Include the EXACT compilation error message
- Reference the specific line that failed
- Mention what was tried before to avoid repetition
- Provide the specific fix needed
"""

def manager_node(state: AgentState) -> AgentState:
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
        }
    
    # Build context with assistant outputs - IMPROVED VERSION
    history_str = ""
    for i, t in enumerate(thoughts):
        history_str += f"Thought {i+1}: {t}\n"
    
    # Include custodian output
    if state.get("custodian_output"):
        history_str += f"\nCustodian's Report: {state['custodian_output']}\n"
    
    # Include coder attempts history - show what failed before
    coder_history = state.get("coder_history", [])
    if coder_history:
        history_str += f"\n=== Previous Code Attempts ({len(coder_history)}) ===\n"
        for idx, attempt in enumerate(coder_history[-2:], 1):  # Only show last 2 attempts
            history_str += f"Attempt {idx}: {'SUCCESS' if attempt.get('success') else 'FAILED'}\n"
            if not attempt.get('success'):
                history_str += f"Error: {attempt.get('error', 'Unknown error')[:300]}\n"
    
    # Include complete evaluator feedback with specific errors
    if state.get("evaluator_output"):
        eval_out = state['evaluator_output']
        history_str += f"\n=== Evaluator's Review ===\n"
        history_str += f"Success: {eval_out.get('success', False)}\n"
        history_str += f"Code Review: {eval_out.get('code_review', 'No review')}\n"
        
        # CRITICAL: Include specific errors for the Coder to see
        if eval_out.get('specific_errors'):
            history_str += f"\n**SPECIFIC ERRORS TO FIX:**\n{eval_out.get('specific_errors')}\n"
        
        # Include raw evaluation output (limited)
        history_str += f"\nRaw Output: {eval_out.get('evaluation', 'No output')[:500]}...\n"
    
    user_msg = (
        f"User question: {state['question']}\n\n"
        f"Previous steps:\n{history_str}\n"
        f"Iteration: {iteration}/{MAX_ITERATIONS}\n\n"
        "Decide which assistant to use next. "
        "IMPORTANT: If there were compilation errors, make sure to pass the EXACT error message and specific fix to the Coder."
    )

    print (f"\n[Manager] Invoking with message:\n{user_msg}\n")
    response = manager_runnable.invoke(
        [
            {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])
    
    print(response)
    thoughts.append(response.thought)
    actions = state.get("actions", [])
    actions.append(
        {
            "assistant": response.assistant,
            "tool_input": response.tool_input,
            "finish": response.finish,
        }
    )

    print(f"\n[Manager] Thought: {response.thought}")
    print(f"[Manager] Next Assistant: {response.assistant}")

    return {
        **state,
        "thoughts": thoughts,
        "actions": actions,
        "iteration": iteration,
    }

def custodian_node(state: AgentState) -> AgentState:
    actions = state.get("actions", [])
    if not actions:
        return state

    last_action = actions[-1]
    tool_input = last_action.get("tool_input")
    
    # Build context of what custodian has gathered so far
    gathered_info = state.get("custodian_output", "None yet.")
    observations = state.get("observations", [])
    recent_obs = "\n".join(observations[-3:]) if observations else "No observations yet."
    
    user_msg = (
        f"Task from Manager: {tool_input}\n\n"
        f"Information gathered so far: {gathered_info}\n\n"
        f"Recent tool results: {recent_obs}\n\n"
        "Decide next tool to use or finish if confident.\n\n"
        "CRITICAL REMINDER:\n"
        "- Only set confident=True if your final_report contains ACTUAL C++ CODE that you've ALREADY retrieved\n"
        "- Code must be visible in 'Recent tool results' above\n"
        "- Do NOT say 'will include' or 'will show' - you must HAVE the code NOW\n"
        "- If you only have example names, you need to read_ns3_example first\n"
        "- Your final_report should have code like: Ptr<LteHelper> lteHelper = CreateObject<LteHelper>(); etc."
    )

    print (f"\n[Custodian] Invoking with message:\n{user_msg}\n")

    response = custodian_runnable.invoke(
        [
            {"role": "system", "content": CUSTODIAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    )
    
    print(f"[Custodian] Response: {response}\n\n")
    
    print(f"\n[Custodian] Tool: {response.next_action}, Confident: {response.confident}")
    
    # VALIDATION: Check if custodian is truly confident with actual code
    actual_confidence = response.confident
    output_to_use = response.final_report if response.confident else response.summary
    
    if response.confident:
        # First check: Has Custodian even called any tools yet?
        observations = state.get("observations", [])
        if not observations or len(observations) == 0:
            print("\n[Custodian] WARNING: Claimed confident but hasn't retrieved any information yet!")
            print("[Custodian] Overriding confident=True to False. Must call tools first.\n")
            actual_confidence = False
            output_to_use = "No information gathered yet. Need to search knowledge base or read examples first."
        else:
            # Verify final_report contains actual code snippets, not just promises
            final_report = response.final_report or ""
            
            # Check for indicators that it's just a promise, not actual code
            promise_indicators = ["will include", "will show", "will provide", "will extract", 
                                 "going to include", "planning to", "next step", "will be"]
            has_promises = any(indicator in final_report.lower() for indicator in promise_indicators)
            
            # Check if it actually has code (look for common C++ patterns)
            code_indicators = ["::", "Ptr<", "CreateObject", "Install", "SetAttribute", "#include", 
                              "MobilityHelper", "LteHelper", "NodeContainer"]
            has_code = any(indicator in final_report for indicator in code_indicators)
            
            # Must have code AND not have promises
            if has_promises or not has_code:
                print("\n[Custodian] WARNING: Claimed confident but final_report lacks actual code snippets!")
                print(f"[Custodian] Has promises: {has_promises}, Has code: {has_code}")
                print(f"[Custodian] Overriding confident=True to False. Continue gathering info.\n")
                actual_confidence = False
                output_to_use = response.summary + "\n\n[NOTE: Need to actually retrieve code snippets, not just plan to do so.]"
    
    # Update actions with custodian's tool choice
    actions.append({
        "tool": response.next_action,
        "tool_input": response.action_input,
        "assistant": "Custodian",
    })
    
    return {
        **state,
        "custodian_output": output_to_use,
        "custodian_confident": actual_confidence,
        "current_assistant": "Custodian",
        "actions": actions,
    }

def coder_node(state: AgentState) -> AgentState:
    actions = state.get("actions", [])
    if not actions:
        return state

    last_action = actions[-1]
    tool_input = last_action.get("tool_input")
    
    # Include custodian context if available
    context = ""
    if state.get("custodian_output"):
        context = f"\nRelevant Documentation/Examples:\n{state['custodian_output']}\n"
    
    # IMPROVED: Include previous failed attempts to avoid repetition
    previous_attempts = ""
    coder_history = state.get("coder_history", [])
    if coder_history:
        previous_attempts = "\n=== PREVIOUS FAILED ATTEMPTS (DO NOT REPEAT) ===\n"
        for idx, attempt in enumerate(coder_history[-2:], 1):
            if not attempt.get('success'):
                previous_attempts += f"\nAttempt {idx} FAILED with error:\n{attempt.get('error', 'Unknown')[:400]}\n"
                previous_attempts += f"Code snippet that failed:\n{attempt.get('code_snippet', 'N/A')}\n"
    
    # IMPROVED: Include specific errors from evaluator
    error_details = ""
    if state.get("evaluator_output") and not state['evaluator_output'].get('success'):
        error_details = f"\n=== COMPILATION/RUNTIME ERRORS TO FIX ===\n{state['evaluator_output'].get('specific_errors', 'See evaluation output')}\n"
    
    user_msg = (
        f"Task: {tool_input}{context}\n"
        f"{previous_attempts}\n"
        f"{error_details}\n"
        f"Important Information for Coding:\n{state.get('custodian_output', 'None')}\n\n"
        "Write the ns-3 simulation code. "
        "CRITICAL: If there are compilation errors above, fix them EXACTLY as specified. Do NOT repeat the same mistakes."
    )

    print (f"\n[Coder] Invoking with message:\n{user_msg}\n")
    response = coder_runnable.invoke(
        [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    )

    print(f"\n[Coder] Generated code, preparing to execute")
    
    # Update actions with coder's tool choice
    tool_input_dict = {"code": response.code, "language": response.language}

    actions.append({
        "tool": "ns3_tool",
        "tool_input": tool_input_dict,
        "assistant": "Coder",
    })
    
    print(f"\n[Coder] Code length: {len(response.code)} characters\n")

    state['coder_output'] = tool_input_dict['code']

    return {
        **state,
        "current_assistant": "Coder",
        "actions": actions,
    }

def act_node(state: AgentState) -> AgentState:
    actions = state.get("actions", [])
    if not actions:
        return state

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
    }

def evaluator_node(state: AgentState) -> AgentState:
    observations = state.get("observations", [])
    code_result = observations[-1]
    generated_code = state.get('coder_output', 'No code available')
        
    user_msg = (
        f"Original Task: {state['question']}\n\n"
        f"Generated Code: {generated_code}\n\n"
        f"Simulation Output: {code_result}\n\n"
        "Evaluate if the simulation meets the requirements.\n"
        "CRITICAL: If there are compilation errors:\n"
        "1. Extract the EXACT error message\n"
        "2. Identify the specific line number\n"
        "3. Explain the error clearly\n"
        "4. Provide the SPECIFIC fix (not general advice)\n"
        "5. Put all error details in 'specific_errors' field\n"
        "Return JSON with 'code_review', 'evaluation', 'success', and 'specific_errors' fields."
    )

    print (f"\n[Evaluator] Invoking with message:\n{user_msg}\n")
    response = evaluator_runnable.invoke(
        [
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    )
    
    print(f"\n[Evaluator] Success: {response.success}")
    print(f"[Evaluator] Evaluation: {response.evaluation[:300]}...")
    if not response.success:
        print(f"[Evaluator] Specific Errors: {response.specific_errors[:300]}...")
    
    # Track this attempt in coder history
    coder_history = state.get("coder_history", [])
    
    # Extract error snippet from the code if compilation failed
    code_snippet = ""
    if not response.success and "error:" in code_result.lower():
        # Try to extract the problematic line from error
        lines = code_result.split('\n')
        for line in lines:
            if 'error:' in line.lower():
                code_snippet += line + "\n"
    
    coder_history.append({
        "code": generated_code[:500],  # Store snippet
        "success": response.success,
        "error": response.specific_errors if not response.success else "",
        "code_snippet": code_snippet,
    })
    
    return {
        **state,
        "evaluator_output": response.model_dump(),
        "coder_history": coder_history,
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
    thoughts_str = "\n".join(
        f"Thought {i+1}: {t}" for i, t in enumerate(state.get("thoughts", []))
    )
    obs_str = "\n".join(
        f"Observation {i+1}: {o[:500]}..." for i, o in enumerate(state.get("observations", []))
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
Write an ns-3 C++ simulation for a cellular network scenario involving mobility and handover. Setup two Base Stations (eNodeBs) placed 100 meters apart and one User Equipment (UE). The UE should move from the first base station towards the second one at a constant velocity of 20 m/s using ConstantVelocityMobilityModel. Enable the X2 interface between base stations to support handover triggers. Run the simulation long enough to capture the handover event."""

    result = app.invoke(
        {
            "question": question,
            "thoughts": [],
            "actions": [],
            "observations": [],
            "iteration": 0,
            "coder_history": [],  # Initialize the new field
        },
        config={"recursion_limit": 50}
    )

    print("=== FINAL ANSWER ===")
    print(result["final_answer"])
