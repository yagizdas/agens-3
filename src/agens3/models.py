"""Structured model responses and graph state for agens-3."""

from typing import Any, Dict, List, TypedDict

from pydantic import BaseModel, Field


class Custodian(BaseModel):
    thought: str = Field(description="Reasoning about what to search or read next")
    next_action: str = Field(
        description="search_knowledge_base|read_ns3_example|list_ns3_examples|null"
    )
    action_input: str = Field(description="Detailed input for the tool (or null if finish=true)")
    summary: str = Field(description="Concise summary of gathered information so far")
    confident: bool = Field(
        description="Set to true when you have enough information to report back"
    )
    final_report: str | None = Field(
        default=None,
        description="Detailed report of relevant gathered information (include only when confident is true)",
    )


class CoderInput(BaseModel):
    code: str = Field(description="The full C++ code for the ns-3 simulation")
    language: str = Field(description="The programming language, usually 'cpp'")


class Coder(BaseModel):
    tool: str = Field(description="ns3_tool")
    tool_input: CoderInput = Field(description="Input for the ns3_tool")


class Evaluator(BaseModel):
    code_review: str = Field(
        description="Detailed code review focusing on correctness, efficiency, and adherence to best practices"
    )
    evaluation: str = Field(description="Output of the terminal after running the code")


class ManagerResponse(BaseModel):
    thought: str = Field(description="Your reasoning")
    assistant: str = Field(description="Custodian|Coder|Evaluator|Null (if finish=true)")
    tool_input: str = Field(
        description="Detailed instructions for the assistant (or null if finish=true)"
    )
    finish: bool = Field(description="true/false")


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
    coder_output: str
    coder_language: str
    evaluator_output: Dict[str, str]
    current_assistant: str
    custodian_iteration: int
    visited_nodes: List[str]
