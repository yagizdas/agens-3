from langchain.tools import tool
import subprocess
import os
import re
from pydantic import BaseModel, Field

TOOL_NAME = "ns-3_tool"
TOOL_DESCRIPTION = """use this tool when you need to simulate ns-3 code.

IMPORTANT: When creating c++ code, make sure to include logging with "NS_LOG_COMPONENT_DEFINE("ns3Agent");"

Input should be a valid ns-3 C++ code or a Python code that uses ns-3 libraries."""

class Ns3ToolInput(BaseModel):
    code: str = Field(..., description="The ns-3 C++ code or Python code to simulate.")
    language: str = Field(..., description="The programming language of the code: 'cpp' or 'python'.")


def validate_cpp_code(code: str) -> tuple[bool, list[str]]:
    """Validate C++ code for common ns-3 API mistakes before compilation"""
    errors = []
    warnings = []
    
    # Check for non-existent methods
    if "lteHelper->AddEnb" in code or "lteHelper.AddEnb" in code:
        errors.append("❌ AddEnb() doesn't exist. Use InstallEnbDevice() instead.")
    
    if "->EnableX2Handover()" in code or ".EnableX2Handover()" in code:
        errors.append("❌ EnableX2Handover() doesn't exist. Use AddX2Interface(enbNodes) or let EpcHelper handle it automatically.")
    
    if "mobility->SetVelocity" in code and "MobilityModel>" in code:
        errors.append("❌ Base MobilityModel doesn't have SetVelocity(). You need GetObject<ConstantVelocityMobilityModel>() first.")
    
    if "Simulator::Schedule" in code and "HandoverRequest" in code:
        # Check if using correct signature (3 args: Time, NetDevice, NetDevice, NetDevice)
        if "Seconds(1.0), &LteHelper::" in code:
            errors.append("❌ Cannot schedule member functions with & syntax. Use MakeCallback or call HandoverRequest directly (it's already scheduling internally).")
    
    # Check for missing includes
    required_includes = {
        "LteHelper": "ns3/lte-module.h",
        "MobilityHelper": "ns3/mobility-module.h",
        "InternetStackHelper": "ns3/internet-module.h",
        "PointToPointEpcHelper": "ns3/lte-module.h",
        "FlowMonitor": "ns3/flow-monitor-module.h",
    }
    
    for class_name, include in required_includes.items():
        if class_name in code and include not in code:
            warnings.append(f"⚠️  Using {class_name} but missing #include \"{include}\"")
    
    # Check for common handover requirements
    if "HandoverRequest" in code or "handover" in code.lower():
        if "epcHelper" not in code.lower() and "EpcHelper" not in code:
            warnings.append("⚠️  Handover typically requires EpcHelper setup. Make sure to create and set it.")
        if "AddX2Interface" not in code:
            warnings.append("⚠️  X2 interface may need to be explicitly added: lteHelper->AddX2Interface(enbNodes)")
    
    # Check for proper Ptr usage
    if re.search(r'lteHelper->Attach\([^,]+Get\(0\),\s*enbNodes\.Get', code):
        errors.append("❌ Attach() expects NetDevice, not Node. Use enbLteDevs.Get(0), not enbNodes.Get(0)")
    
    return len(errors) == 0, errors + warnings


def parse_compilation_error(error_text: str) -> dict:
    """Extract actionable information from compilation errors"""
    info = {
        "error_type": "unknown",
        "problematic_code": None,
        "suggestion": None,
        "line_number": None,
    }
    
    # Extract line number
    line_match = re.search(r':(\d+):\d+: error:', error_text)
    if line_match:
        info["line_number"] = line_match.group(1)
    
    if "no member named" in error_text:
        info["error_type"] = "missing_member"
        match = re.search(r"no member named '(\w+)' in '([^']+)'", error_text)
        if match:
            member, class_name = match.groups()
            info["problematic_code"] = f"{class_name}::{member}"
            
            # Provide specific suggestions
            suggestions = {
                "AddEnb": "Use InstallEnbDevice(enbNodes) instead",
                "EnableX2Handover": "Use AddX2Interface(enbNodes) or rely on EpcHelper",
                "SetVelocity": "Cast to ConstantVelocityMobilityModel first: ueNode->GetObject<ConstantVelocityMobilityModel>()",
            }
            info["suggestion"] = suggestions.get(member, f"Method {member}() doesn't exist in {class_name}. Check documentation or examples.")
    
    elif "use of undeclared identifier" in error_text:
        info["error_type"] = "undeclared_identifier"
        match = re.search(r"use of undeclared identifier '(\w+)'", error_text)
        if match:
            identifier = match.group(1)
            info["problematic_code"] = identifier
            
            # Common fixes
            if "MobilityHelper" in identifier:
                info["suggestion"] = "Add #include \"ns3/mobility-module.h\""
            elif "EpcHelper" in identifier or "Epc" in identifier:
                info["suggestion"] = "Add #include \"ns3/lte-module.h\" (includes EPC helpers)"
            else:
                info["suggestion"] = f"Missing #include or wrong type name for {identifier}"
    
    elif "cannot initialize" in error_text and "NetDevice" in error_text and "Node" in error_text:
        info["error_type"] = "type_mismatch"
        info["problematic_code"] = "Attach() call"
        info["suggestion"] = "Use enbLteDevs.Get(0) not enbNodes.Get(0). Attach needs NetDevice, not Node."
    
    return info


@tool("ns-3_tool", description=TOOL_DESCRIPTION, args_schema=Ns3ToolInput)
def Ns3Tool(code: str, language: str) -> str:
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
        # Validate code before attempting compilation
        is_valid, messages = validate_cpp_code(cpp_code)
        
        if not is_valid:
            error_msg = "🔍 Code Validation Failed - Issues detected:\n\n"
            error_msg += "\n".join(messages)
            error_msg += "\n\n💡 Suggestion: Use read_ns3_example tool to see correct API usage, or fix the issues above."
            return error_msg
        
        # Show warnings but continue
        if messages:
            print("⚠️  Validation warnings:")
            for msg in messages:
                print(f"  {msg}")
        
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
                timeout=300,  # 5 minute timeout
                env={**os.environ, "NS_LOG": "ns3Agent=info"}
            )
            
            combined_output = result.stdout + result.stderr

            # Check if there was an error
            if result.returncode != 0:
                # Parse error for helpful information
                error_info = parse_compilation_error(combined_output)
                
                error_msg = f"❌ Simulation failed with return code {result.returncode}\n\n"
                
                if error_info["error_type"] != "unknown":
                    error_msg += f"📍 Error Type: {error_info['error_type']}\n"
                    if error_info["line_number"]:
                        error_msg += f"📍 Line: {error_info['line_number']}\n"
                    if error_info["problematic_code"]:
                        error_msg += f"📍 Problem: {error_info['problematic_code']}\n"
                    if error_info["suggestion"]:
                        error_msg += f"💡 Suggestion: {error_info['suggestion']}\n"
                    error_msg += "\n"
                
                error_msg += f"Full Output:\n{combined_output}"
                
                print(error_msg)
                return error_msg
            
            # Success case - filter noise
            filtered_output = '\n'.join(
                line for line in combined_output.split('\n') 
                if not any(keyword in line for keyword in 
                          ["Building CXX", "Linking CXX", "[  ", "[ "])
            )
            
            if not filtered_output.strip():
                filtered_output = combined_output
            
            success_msg = f"✅ Simulation completed successfully.\n\nOutput:\n{filtered_output}"
            return success_msg
            
        except subprocess.TimeoutExpired:
            return f"⏱️  Simulation timed out after 300 seconds"
        except Exception as e:
            return f"An error occurred during execution: {str(e)}"

    return run_ns3_simulation(code, language)
