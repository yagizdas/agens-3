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

client = OpenAI()

class CoderInput(BaseModel):
    code: str = Field(description="The full C++ code for the ns-3 simulation")
    language: str = Field(description="The programming language, usually 'cpp'")

class Coder(BaseModel):
    tool: str = Field(description="ns3_tool")
    tool_input: CoderInput = Field(description="Input for the ns3_tool")

CODER_SYSTEM_PROMPT = """You are the Coder Assistant, an expert ns-3 network simulator coder. 
Your Manager provides you with detailed simulation guidelines to implement alongside with any relevant documentation or example code. 
Your ONLY role is to write ns-3 simulation code.
You will use the ns3_tool to compile and run your simulation:

1. "ns3_tool" - Compile and run ns-3 simulation
   Input: {"code": "<full_cpp_code>", "language": "cpp"}
    - IMPORTANT: When creating ns-3 simulation code, make sure to include logging with "NS_LOG_COMPONENT_DEFINE("ns3Agent");"
"""

if __name__ == "__main__":
    query = """
Write an NS-3 simulation script that replicates that should establish a Point-to-Point link between two nodes with DataRate set to '5Mbps' and Delay to '2ms'. Exchange a single packet using UdpEcho Client and Server applications. Enable logging for the UdpEcho applications so the console displays the packet transmission and reception times.
    """
    resp = client.responses.parse(
    model = gpt_model,
    input = [
        {"role": "system", "content": CODER_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ],
    text_format=Coder
    )
    response = resp.output_parsed

    tool_input_dict = response.tool_input.model_dump() 
    print(Ns3Tool.run(tool_input_dict))

