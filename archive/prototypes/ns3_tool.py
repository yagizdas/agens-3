from langchain.tools import tool
import subprocess
import os
from pydantic import BaseModel, Field

TOOL_NAME = "ns-3_tool"
TOOL_DESCRIPTION = """use this tool when you need to simulate ns-3 code.

IMPORTANT: When creating c++ code, make sure to include logging with "NS_LOG_COMPONENT_DEFINE("ns3Agent");"

Input should be a valid ns-3 C++ code or a Python code that uses ns-3 libraries."""

class Ns3ToolInput(BaseModel):
    code: str = Field(..., description="The ns-3 C++ code or Python code to simulate.")
    language: str = Field(..., description="The programming language of the code: 'cpp' or 'python'.")

@tool("ns-3_tool", description=TOOL_DESCRIPTION, args_schema=Ns3ToolInput)
def Ns3Tool(code: str, language:str) -> str:
    def run_ns3_simulation(code: str, language: str) -> str:
        print("Tool Invoked with params: ", code[:50], language)
        if language == 'python':
            return run_python_simulation(code)
        elif language == 'cpp':
            return run_cpp_simulation(code)
        else:
            return "Invalid Language."
    
    def run_python_simulation(python_code: str):
        simulated_file_code = """
        import os
        import sys
        if not hasattr(sys, 'argv'):
            sys.argv  = ['']
        __file__ = os.path.abspath('<simulated_file>')
        """ + python_code

        try:
            result = subprocess.run(["python", "-c", simulated_file_code], capture_output=True, text=True)
            combined_output = result.stdout + result.stderr
            filtered_output = '\n'.join(
                line for line in combined_output.split('\n') 
                if not ("Fail" in line or "Warning" in line or "warning" in line or "fail" in line)
            )
            print(f"{filtered_output}")
            return f"{filtered_output}"
        
        except Exception as e:
            return f"An error occurred during execution: {e}"

    def run_cpp_simulation(cpp_code: str):
        ns3_file_path = "/Users/kemalyagizdaskiran/Desktop/ns-3.46.1/scratch/reAct-ive-5G.cc"
        ns3_dir = "/Users/kemalyagizdaskiran/Desktop/ns-3.46.1"
        
        try:
            with open(ns3_file_path, 'w') as file:
                file.write(cpp_code)
        except Exception as e:
            return f"An error occurred while writing to the file: {e}"
        
        try:
            # Run the simulation and wait for it to complete
            result = subprocess.run(
                ["./ns3", "run", "reAct-ive-5G"], 
                cwd=ns3_dir, 
                capture_output=True, 
                text=True,
                timeout=300,  # 5 minute timeout to prevent hanging
                env={**os.environ, "NS_LOG": "ns3Agent=info"}

            )
            
            combined_output = result.stdout + result.stderr

            # Check if there was an error
            if result.returncode != 0:
                print(f"Simulation failed with return code {result.returncode}")
                return f"Simulation failed with return code {result.returncode}\n\nOutput:\n{combined_output}"
            
            # Filter out build messages and warnings
            filtered_output = '\n'.join(
                line for line in combined_output.split('\n') 
                if not any(keyword in line for keyword in ["Fail", "Warning", "warning", "fail", "Building CXX", "Linking CXX", "[  0%]", "[ "])
            )

            filtered_output = combined_output
            
            # If filtered output is empty, return the full output
            if not filtered_output.strip():
                print(f"Full output:\n{combined_output}")
                return f"Simulation completed successfully.\n\nFull output:\n{combined_output}"
            
            return f"Simulation completed successfully.\n\nOutput:\n{filtered_output}"
            
        except subprocess.TimeoutExpired:
            return f"Simulation timed out after 300 seconds"
        except Exception as e:
            return f"An error occurred during execution. REWRITE THE WHOLE CODE IN A DIFFERENT WAY."
            

    return run_ns3_simulation(code, language)

