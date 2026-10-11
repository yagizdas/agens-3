from typing import TypedDict, List, Any, Dict, Optional

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
from search_knowledge_base_tool import create_search_knowledge_base_tool
from initialize_knowledge_base import initialize_knowledge_base
from read_example_tool import read_ns3_example, list_ns3_examples

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Initialize collection once
knowledge_base_collection = initialize_knowledge_base()

cpp_tool = CppSubprocessTool(allow_dangerous_code=True)
search_tool = DuckDuckGoSearchRun()
python_repl_tool = PythonREPLTool()
search_knowledge_base_tool = create_search_knowledge_base_tool(knowledge_base_collection)

tools = {
    "search": search_tool, 
    "cpp": cpp_tool, 
    "python_repl": python_repl_tool, 
    "ns3_tool": Ns3Tool, 
    "search_knowledge_base": search_knowledge_base_tool,
    "read_ns3_example": read_ns3_example,        
    "list_ns3_examples": list_ns3_examples       
}

# ============================================================================
# MULTI-AGENT STATE STRUCTURE
# ============================================================================

class SubTask(TypedDict, total=False):
    """Represents a sub-task in the DAG plan"""
    task_id: str
    description: str
    type: str  # e.g., "topology", "protocol", "traffic", "data_collection"
    status: str  # "pending", "in_progress", "completed", "failed"
    dependencies: List[str]  # List of task_ids this depends on
    result: Optional[str]

class AgentState(TypedDict, total=False):
    # User input
    question: str
    
    # Manager's plan (DAG of sub-tasks)
    plan: List[SubTask]
    current_task_id: Optional[str]
    
    # Repository Custodian outputs
    rag_context: List[str]  # Retrieved documentation
    rag_level: str  # "summary", "api", "code_example"
    
    # Developer outputs
    generated_code: Optional[str]
    code_iteration: int
    
    # QA Engineer outputs
    simulation_output: Optional[str]
    test_results: Optional[Dict[str, Any]]
    bug_reports: List[str]
    
    # Self-Reflection outputs
    reflection_feedback: List[str]
    code_quality_issues: List[str]
    
    # Global state
    messages: List[str]  # Communication log between agents
    iteration: int
    final_answer: str
    is_complete: bool


# ============================================================================
# MANAGER/ORCHESTRATOR AGENT
# ============================================================================

MANAGER_SYSTEM_PROMPT = """You are the Manager/Orchestrator for ns-3 simulation tasks.

Your role:
1. Break down the user's query into logical sub-problems (sub-tasks)
2. Create a DAG (Directed Acyclic Graph) plan with dependencies
3. Coordinate other specialized agents
4. Track progress and adjust the plan as needed

Sub-task types you can create:
- "topology": Define network topology (nodes, links, channels)
- "protocol": Configure protocol stack (WiFi, LTE, TCP/IP, etc.)
- "traffic": Set up traffic patterns (applications, flows)
- "data_collection": Configure metrics, tracing, logging
- "validation": Verify correctness of setup

For each sub-task, specify:
- task_id: unique identifier
- description: what needs to be done
- type: one of the above types
- dependencies: list of task_ids that must complete first

Respond with JSON:
{
  "plan": [
    {
      "task_id": "task_1",
      "description": "...",
      "type": "topology",
      "dependencies": []
    },
    ...
  ],
  "current_task_id": "task_1",
  "message": "explanation of the plan"
}
"""

def manager_node(state: AgentState) -> AgentState:
    """Manager breaks down the user query into a structured plan"""
    
    # If plan already exists, check progress and update current task
    if state.get("plan"):
        plan = state["plan"]
        
        # Find next task to execute
        for task in plan:
            if task["status"] == "pending":
                # Check if dependencies are met
                deps_met = all(
                    any(t["task_id"] == dep_id and t["status"] == "completed" 
                        for t in plan)
                    for dep_id in task.get("dependencies", [])
                )
                
                if deps_met or not task.get("dependencies"):
                    messages = state.get("messages", [])
                    messages.append(f"Manager: Proceeding with {task['task_id']}: {task['description']}")
                    
                    return {
                        **state,
                        "current_task_id": task["task_id"],
                        "messages": messages,
                    }
        
        # All tasks completed
        messages = state.get("messages", [])
        messages.append("Manager: All sub-tasks completed. Finalizing.")
        return {
            **state,
            "is_complete": True,
            "messages": messages,
        }
    
    # Create initial plan
    user_msg = (
        f"User question: {state['question']}\n\n"
        "Break this down into a structured plan with sub-tasks."
    )
    
    resp = llm.invoke([
        {"role": "system", "content": MANAGER_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    print(resp.content)
    try:
        parsed = json.loads(resp.content)
        plan = parsed.get("plan", [])
        
        # Initialize task statuses
        for task in plan:
            task["status"] = "pending"
            task["result"] = None
        
        messages = state.get("messages", [])
        messages.append(f"Manager: {parsed.get('message', 'Created plan')}")
        
        print(f"Manager created plan with {len(plan)} tasks")
        for task in plan:
            print(f"  - {task['task_id']}: {task['description']}")
        
        return {
            **state,
            "plan": plan,
            "current_task_id": parsed.get("current_task_id"),
            "messages": messages,
            "iteration": state.get("iteration", 0) + 1,
        }
    except Exception as e:
        print(f"Manager parsing error: {e}")
        return {
            **state,
            "is_complete": True,
            "final_answer": f"Failed to create plan: {str(e)}",
        }

# ============================================================================
# REPOSITORY CUSTODIAN (RAG SPECIALIST) AGENT
# ============================================================================

CUSTODIAN_SYSTEM_PROMPT = """You are the Repository Custodian, a RAG specialist for ns-3 documentation.

Your ONLY role is to find and retrieve the correct API documentation. You do NOT write code for production. However, you can explain code.

You have access to a 2-level hierarchical knowledge base:
- Level 1 (Summary): High-level guides and tutorials
- Level 2 (API): Specific class references and method signatures

Given a task, determine:
1. Which level(s) to search
2. What keywords to use
3. What information to retrieve

Respond with JSON:
{
  "search_strategy": "summary|api",
  "keywords": ["keyword1", "keyword2"],
  "searches": [
    {"level": "api", "query": "WifiPhy SetTxPowerStart"},
    {"level": "summary", "query": "wifi transmission power"}
  ],
  "message": "explanation of search strategy"
}
"""

def custodian_node(state: AgentState) -> AgentState:
    """Repository Custodian retrieves relevant documentation"""
    
    current_task_id = state.get("current_task_id")
    if not current_task_id:
        return state
    
    plan = state.get("plan", [])
    current_task = next((t for t in plan if t["task_id"] == current_task_id), None)
    
    if not current_task:
        return state
    
    # Build context from previous retrievals
    rag_context = state.get("rag_context", [])
    
    user_msg = (
        f"Current task: {current_task['description']}\n"
        f"Task type: {current_task['type']}\n"
        f"Previous context retrieved: {len(rag_context)} items\n\n"
        "What documentation should I retrieve?"
    )
    
    print("Custodian getting invoked with params:", user_msg)
    resp = llm.invoke([
        {"role": "system", "content": CUSTODIAN_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    
    print(resp.content)
    try:
        parsed = json.loads(resp.content)
        searches = parsed.get("searches", [])
        
        # Perform searches based on strategy
        new_context = []
        for search in searches:
            level = search.get("level", "api")
            query = search.get("query", "")
            
            if level == "code_example":
                # For code examples, try to find actual ns-3 example files
                # Extract module from task description or type
                module_keywords = {
                    "wifi": "wifi",
                    "lte": "lte", 
                    "802.11": "wifi",
                    "handover": "lte",
                    "tcp": "applications",
                    "udp": "applications",
                    "mobility": "mobility"
                }
                
                module = "lte"  # default
                task_desc_lower = current_task['description'].lower()
                for keyword, mod in module_keywords.items():
                    if keyword in task_desc_lower:
                        module = mod
                        break
                
                # List examples first
                examples_list = list_ns3_examples.run(module)
                new_context.append(f"[Level: CODE_EXAMPLE] {examples_list}")
                
            else:
                # Use hierarchical search_knowledge_base for summary and API levels
                results = search_knowledge_base_tool.run({
                    "keyword": query,
                    "level": level
                })
                new_context.extend(results if isinstance(results, list) else [results])
        
        rag_context.extend(new_context)
        
        messages = state.get("messages", [])
        messages.append(f"Custodian: Retrieved {len(new_context)} documentation items")
        
        print(f"Custodian retrieved {len(new_context)} items")
        
        return {
            **state,
            "rag_context": rag_context,
            "rag_level": parsed.get("search_strategy", "api"),
            "messages": messages,
        }
    except Exception as e:
        print(f"Custodian error: {e}")
        return state

# ============================================================================
# DEVELOPER (CODER) AGENT
# ============================================================================

DEVELOPER_SYSTEM_PROMPT = """You are the Developer agent responsible for writing ns-3 C++ simulation code.

Your role:
1. Write correct, executable ns-3 C++ code based on:
   - The current task from the Manager
   - Documentation provided by the Custodian
   - Feedback from the QA Engineer
   - Critiques from the Self-Reflection agent

2. Follow ns-3 best practices:
   - Include proper logging: NS_LOG_COMPONENT_DEFINE("ns3Agent");
   - Use smart pointers correctly (Ptr<T>)
   - Schedule simulation events properly
   - Output required metrics to std::cout

3. Print these metrics at the end:
   - Total Packet Loss
   - Average Delay (ms)
   - Average Throughput (Mbps)

Respond with JSON:
{
  "code": "full C++ code here",
  "language": "cpp",
  "explanation": "what this code does",
  "message": "any notes or concerns"
}
"""

def developer_node(state: AgentState) -> AgentState:
    """Developer writes the ns-3 simulation code"""
    
    current_task_id = state.get("current_task_id")
    if not current_task_id:
        return state
    
    plan = state.get("plan", [])
    current_task = next((t for t in plan if t["task_id"] == current_task_id), None)
    
    if not current_task:
        return state
    
    # Gather context for code generation
    rag_context = state.get("rag_context", [])
    bug_reports = state.get("bug_reports", [])
    reflection_feedback = state.get("reflection_feedback", [])
    code_iteration = state.get("code_iteration", 0)
    
    # Build comprehensive context
    context_str = f"Task: {current_task['description']}\n\n"
    
    if rag_context:
        context_str += "Documentation:\n" + "\n".join(rag_context[-3:]) + "\n\n"
    
    if bug_reports:
        context_str += "Bug reports from QA:\n" + "\n".join(bug_reports[-2:]) + "\n\n"
    
    if reflection_feedback:
        context_str += "Reflection feedback:\n" + "\n".join(reflection_feedback[-2:]) + "\n\n"
    
    context_str += f"Iteration: {code_iteration + 1}/5"
    
    resp = llm.invoke([
        {"role": "system", "content": DEVELOPER_SYSTEM_PROMPT},
        {"role": "user", "content": context_str},
    ])
    
    try:
        parsed = json.loads(resp.content)
        code = parsed.get("code", "")
        
        messages = state.get("messages", [])
        messages.append(f"Developer: Generated code ({len(code)} chars)")
        
        print(f"Developer generated code (iteration {code_iteration + 1})")
        
        return {
            **state,
            "generated_code": code,
            "code_iteration": code_iteration + 1,
            "messages": messages,
        }
    except Exception as e:
        print(f"Developer error: {e}")
        return state

# ============================================================================
# QA ENGINEER (TESTER) AGENT
# ============================================================================

QA_SYSTEM_PROMPT = """You are the QA Engineer responsible for testing ns-3 simulations.

Your role:
1. Execute the simulation code using the ns3_tool
2. Analyze the output for:
   - Compilation errors
   - Runtime errors
   - Incorrect results
   - Missing metrics

3. Generate structured bug reports with:
   - Error type (compilation, runtime, logic)
   - Specific error messages
   - Suggested fixes
   - Line numbers if applicable

4. Extract and validate metrics:
   - Packet Loss
   - Delay
   - Throughput

Respond with JSON:
{
  "test_passed": true/false,
  "metrics": {
    "packet_loss": value,
    "avg_delay_ms": value,
    "avg_throughput_mbps": value
  },
  "bug_report": "detailed structured report if test failed",
  "message": "summary"
}
"""

def qa_engineer_node(state: AgentState) -> AgentState:
    """QA Engineer tests the code and reports issues"""
    
    code = state.get("generated_code")
    if not code:
        return state
    
    # Run the simulation
    print("QA Engineer: Running simulation...")
    try:
        result = Ns3Tool.run({
            "code": code,
            "language": "cpp"
        })
        
        messages = state.get("messages", [])
        
        # Analyze the output
        user_msg = (
            f"Simulation output:\n{result}\n\n"
            "Analyze this output and extract metrics or identify errors."
        )
        
        resp = llm.invoke([
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])
        
        parsed = json.loads(resp.content)
        test_passed = parsed.get("test_passed", False)
        
        bug_reports = state.get("bug_reports", [])
        if not test_passed and parsed.get("bug_report"):
            bug_reports.append(parsed["bug_report"])
        
        messages.append(f"QA: {'✓ Test passed' if test_passed else '✗ Test failed'}")
        
        print(f"QA Engineer: {'PASS' if test_passed else 'FAIL'}")
        
        # Update current task status
        plan = state.get("plan", [])
        current_task_id = state.get("current_task_id")
        for task in plan:
            if task["task_id"] == current_task_id:
                if test_passed:
                    task["status"] = "completed"
                    task["result"] = str(parsed.get("metrics"))
                else:
                    task["status"] = "in_progress"  # Retry with fixes
        
        return {
            **state,
            "simulation_output": result,
            "test_results": parsed.get("metrics"),
            "bug_reports": bug_reports,
            "plan": plan,
            "messages": messages,
        }
        
    except Exception as e:
        print(f"QA Engineer error: {e}")
        bug_reports = state.get("bug_reports", [])
        bug_reports.append(f"Execution error: {str(e)}")
        
        messages = state.get("messages", [])
        messages.append(f"QA: Execution failed - {str(e)}")
        
        return {
            **state,
            "bug_reports": bug_reports,
            "messages": messages,
        }

# ============================================================================
# SELF-REFLECTION AGENT
# ============================================================================

REFLECTION_SYSTEM_PROMPT = """You are the Self-Reflection agent, a persistent code critic.

Your role is to review the generated code for quality issues BEFORE testing:

Check for:
1. Smart pointer usage (Ptr<T> casting, dereferencing)
2. Event scheduling (Simulator::Schedule, Simulator::Stop)
3. Memory management (CreateObject, Install methods)
4. NS-3 API correctness (method signatures, namespaces)
5. Logging and output (NS_LOG, std::cout for metrics)
6. Edge cases and error handling

Provide constructive critique:
- Point out specific issues with line references
- Suggest corrections
- Highlight potential runtime errors
- Verify best practices

Respond with JSON:
{
  "has_issues": true/false,
  "issues": [
    {"type": "smart_pointer", "description": "...", "suggestion": "..."},
    ...
  ],
  "code_quality_score": 0-10,
  "message": "overall assessment"
}
"""

def reflection_node(state: AgentState) -> AgentState:
    """Self-Reflection agent critiques the code quality"""
    
    code = state.get("generated_code")
    if not code:
        return state
    
    user_msg = (
        f"Review this ns-3 code:\n\n```cpp\n{code}\n```\n\n"
        "Identify any quality issues or potential bugs."
    )
    
    resp = llm.invoke([
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    
    try:
        parsed = json.loads(resp.content)
        has_issues = parsed.get("has_issues", False)
        issues = parsed.get("issues", [])
        
        reflection_feedback = state.get("reflection_feedback", [])
        code_quality_issues = state.get("code_quality_issues", [])
        
        if has_issues:
            feedback_msg = f"Quality score: {parsed.get('code_quality_score', 0)}/10\n"
            feedback_msg += "\n".join(f"- {issue['type']}: {issue['description']}" 
                                     for issue in issues)
            reflection_feedback.append(feedback_msg)
            code_quality_issues.extend(
                f"{issue['type']}: {issue['suggestion']}" for issue in issues
            )
        
        messages = state.get("messages", [])
        messages.append(f"Reflection: {parsed.get('message', 'Code reviewed')}")
        
        print(f"Reflection: {len(issues)} issues found")
        
        return {
            **state,
            "reflection_feedback": reflection_feedback,
            "code_quality_issues": code_quality_issues,
            "messages": messages,
        }
    except Exception as e:
        print(f"Reflection error: {e}")
        return state


# ============================================================================
# FINAL ANSWER NODE
# ============================================================================

FINAL_SYSTEM_PROMPT = """Provide a clear, concise final answer based on the multi-agent workflow.

Summarize:
1. What was accomplished
2. Key metrics obtained from simulations
3. Any important insights

Focus on results and numerical outcomes. The user is more interested in simulation metrics 
(throughput, delay, packet loss) than internal agent coordination details."""

def final_answer_node(state: AgentState) -> AgentState:
    """Generate final answer from all agent outputs"""
    
    plan = state.get("plan", [])
    test_results = state.get("test_results", {})
    messages = state.get("messages", [])
    
    plan_summary = "\n".join(
        f"{task['task_id']}: {task['status']} - {task.get('result', 'N/A')}"
        for task in plan
    )
    
    agent_log = "\n".join(messages[-10:])  # Last 10 messages
    
    user_msg = (
        f"User question: {state['question']}\n\n"
        f"Task execution summary:\n{plan_summary}\n\n"
        f"Final metrics: {test_results}\n\n"
        f"Agent coordination log:\n{agent_log}\n\n"
        "Provide a helpful final answer."
    )
    
    resp = llm.invoke([
        {"role": "system", "content": FINAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    
    return {
        **state,
        "final_answer": resp.content,
    }

# ============================================================================
# ROUTING LOGIC
# ============================================================================

def route_after_manager(state: AgentState) -> str:
    """Route after Manager decides the plan"""
    if state.get("is_complete"):
        return "final"
    
    # Manager created a plan, now get documentation
    return "custodian"

def route_after_custodian(state: AgentState) -> str:
    """Route after Custodian retrieves documentation"""
    # Move to Developer to write code
    return "developer"

def route_after_developer(state: AgentState) -> str:
    """Route after Developer writes code"""
    # Get reflection feedback before testing
    return "reflection"

def route_after_reflection(state: AgentState) -> str:
    """Route after Reflection reviews code"""
    reflection_feedback = state.get("reflection_feedback", [])
    code_iteration = state.get("code_iteration", 0)
    
    # If serious issues and haven't retried too many times, go back to developer
    code_quality_issues = state.get("code_quality_issues", [])
    if len(code_quality_issues) > 3 and code_iteration < 3:
        return "developer"
    
    # Otherwise proceed to testing
    return "qa"

def route_after_qa(state: AgentState) -> str:
    """Route after QA tests the code"""
    bug_reports = state.get("bug_reports", [])
    code_iteration = state.get("code_iteration", 0)
    
    # Check if current task passed
    plan = state.get("plan", [])
    current_task_id = state.get("current_task_id")
    current_task = next((t for t in plan if t["task_id"] == current_task_id), None)
    
    if current_task and current_task["status"] == "completed":
        # Task completed, go back to manager to get next task
        return "manager"
    
    # Task failed - retry if we haven't exceeded max iterations
    if code_iteration < 5:
        # Go back to developer with bug reports
        return "developer"
    else:
        # Too many failures, move on
        return "manager"

# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

from langgraph.graph import StateGraph, END

graph = StateGraph(AgentState)

# Add all agent nodes
graph.add_node("manager", manager_node)
graph.add_node("custodian", custodian_node)
graph.add_node("developer", developer_node)
graph.add_node("reflection", reflection_node)
graph.add_node("qa", qa_engineer_node)
graph.add_node("final", final_answer_node)

# Set entry point
graph.set_entry_point("manager")

# Define edges with routing
graph.add_conditional_edges(
    "manager",
    route_after_manager,
    {
        "custodian": "custodian",
        "final": "final",
    }
)

graph.add_edge("custodian", "developer")

graph.add_conditional_edges(
    "developer",
    route_after_developer,
    {
        "reflection": "reflection",
    }
)

graph.add_conditional_edges(
    "reflection",
    route_after_reflection,
    {
        "developer": "developer",
        "qa": "qa",
    }
)

graph.add_conditional_edges(
    "qa",
    route_after_qa,
    {
        "developer": "developer",
        "manager": "manager",
    }
)

graph.add_edge("final", END)

app = graph.compile()

# Visualize the graph
try:
    mermaid_image = app.get_graph().draw_mermaid_png()
except:
    mermaid_image = None

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":

    question = """
Create an ns-3 simulation script using C++. Simulate an IEEE 802.11ax (Wi-Fi 6) infrastructure network with one Access Point (AP) and a variable number of Stations (STAs). The number of stations should be defined as a command-line argument named 'nWifi' with a default value of 10. Install the Internet stack and set up a UDP echo server on the AP and clients on all STAs. Ensure the simulation supports scaling up to 100 nodes efficiently.
"""

    result = app.invoke(
        {
            "question": question,
            "plan": [],
            "current_task_id": None,
            "rag_context": [],
            "generated_code": None,
            "code_iteration": 0,
            "simulation_output": None,
            "test_results": None,
            "bug_reports": [],
            "reflection_feedback": [],
            "code_quality_issues": [],
            "messages": [],
            "iteration": 0,
            "is_complete": False,
        },
        {"recursion_limit": 50}  # Allow more iterations for multi-agent workflow
    )

    print("\n" + "="*80)
    print("=== FINAL ANSWER ===")
    print("="*80)
    print(result.get("final_answer", "No final answer generated"))
    
    print("\n" + "="*80)
    print("=== EXECUTION PLAN ===")
    print("="*80)
    for task in result.get("plan", []):
        print(f"{task['task_id']}: {task['description']}")
        print(f"  Status: {task['status']}")
        print(f"  Result: {task.get('result', 'N/A')}")
    
    print("\n" + "="*80)
    print("=== METRICS ===")
    print("="*80)
    print(json.dumps(result.get("test_results", {}), indent=2))
    
    print("\n" + "="*80)
    print("=== AGENT COMMUNICATION LOG ===")
    print("="*80)
    for msg in result.get("messages", []):
        print(f"  {msg}")