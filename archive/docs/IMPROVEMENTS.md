# Architectural Improvements for ns-3 Agent

## Critical Issues Identified

### 1. **No Example Code Retrieval**
**Problem**: Agent searches documentation but never looks at actual working code examples.

**Solution**: Add a new tool to search and read example files:

```python
# Add to langgraphagent.py
from langchain.tools import tool

@tool
def read_ns3_example(example_name: str) -> str:
    """Read an ns-3 example file by name (e.g., 'lena-x2-handover').
    Searches in /Users/kemalyagizdaskiran/Desktop/ns-3.46.1/src/*/examples/"""
    import glob
    
    base_path = "/Users/kemalyagizdaskiran/Desktop/ns-3.46.1"
    patterns = [
        f"{base_path}/src/*/examples/{example_name}.cc",
        f"{base_path}/examples/**/{example_name}.cc"
    ]
    
    for pattern in patterns:
        files = glob.glob(pattern, recursive=True)
        if files:
            with open(files[0], 'r') as f:
                return f.read()
    
    return f"Example {example_name} not found"

# Add to tools dict
tools["read_ns3_example"] = read_ns3_example
```

### 2. **Improve System Prompt with API Patterns**

**Problem**: Agent doesn't know common ns-3 patterns.

**Solution**: Enhance REASON_SYSTEM_PROMPT with concrete examples:

```python
REASON_SYSTEM_PROMPT = """You are an ns-3 simulation expert that reasons step-by-step.

NS-3 CRITICAL PATTERNS YOU MUST FOLLOW:

1. LTE Handover Setup:
   - MUST use EpcHelper: `Ptr<PointToPointEpcHelper> epcHelper = CreateObject<PointToPointEpcHelper>();`
   - Set EPC: `lteHelper->SetEpcHelper(epcHelper);`
   - Install devices: `NetDeviceContainer enbDevs = lteHelper->InstallEnbDevice(enbNodes);`
   - Attach UE: `lteHelper->Attach(ueLteDevs.Get(0), enbLteDevs.Get(0));`

2. Manual Handover:
   ```cpp
   lteHelper->HandoverRequest(Seconds(0.100), 
                              ueLteDevs.Get(0), 
                              enbLteDevs.Get(0), 
                              enbLteDevs.Get(1));
   ```

3. Mobility with Velocity:
   ```cpp
   MobilityHelper mobility;
   mobility.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
   mobility.Install(ueNodes);
   
   // Set velocity AFTER installation
   Ptr<ConstantVelocityMobilityModel> mob = 
       ueNodes.Get(0)->GetObject<ConstantVelocityMobilityModel>();
   mob->SetVelocity(Vector(20, 0, 0));
   ```

4. X2 Interface:
   - Automatically enabled when using EpcHelper
   - For explicit setup: `lteHelper->AddX2Interface(enbNodes);`

WORKFLOW:
1. If task involves handover/LTE → search_knowledge_base for relevant examples
2. When documentation mentions an example (e.g., "lena-x2-handover") → use read_ns3_example tool
3. Study the example code structure before writing your own
4. On compilation errors → read the working example again and compare

Available tools:
- "read_ns3_example": Read ns-3 example source code. Input: example name (e.g., "lena-x2-handover")
- "search_knowledge_base": Search ns-3 documentation. Input: search keywords
- "ns3_tool": Simulate code. Input: {"code": "...", "language": "cpp"}
- "search": Web search via DuckDuckGo
- "python_repl": Execute Python code

CRITICAL: For ns-3_tool, tool_input must be: {"code": "...", "language": "cpp"}
"""
```

### 3. **Add Error Recovery with Example Comparison**

**Problem**: Agent repeats same mistakes without learning.

**Solution**: Add a reflection mechanism:

```python
def reason_node(state: AgentState) -> AgentState:
    # ... existing code ...
    
    # Check for repeated compilation errors
    observations = state.get("observations", [])
    if len(observations) > 0:
        last_obs = observations[-1]
        if "error:" in last_obs.lower() and "Building CXX" in last_obs:
            # Extract error type
            if "no member named" in last_obs:
                # Suggest reading working example
                history_str += "\nNOTE: Compilation error detected. Consider using read_ns3_example to see correct API usage.\n"
    
    # ... rest of code ...
```

### 4. **Add Code Validation Before Simulation**

**Problem**: Agent doesn't catch obvious mistakes before compiling.

**Solution**: Add validation in ns3_tool.py:

```python
def validate_cpp_code(code: str) -> tuple[bool, str]:
    """Basic validation before attempting to compile"""
    errors = []
    
    # Check for common mistakes
    if "lteHelper->AddEnb" in code:
        errors.append("AddEnb() doesn't exist. Use InstallEnbDevice() instead.")
    
    if "lteHelper->EnableX2Handover()" in code:
        errors.append("EnableX2Handover() doesn't exist. Use AddX2Interface() or let EpcHelper handle it.")
    
    if "mobility->SetVelocity" in code and "MobilityModel>" in code:
        errors.append("MobilityModel doesn't have SetVelocity(). Cast to ConstantVelocityMobilityModel first.")
    
    if "LteHelper" in code and "epcHelper" not in code.lower():
        errors.append("WARNING: LTE handover typically requires EpcHelper setup.")
    
    if errors:
        return False, "\n".join(errors)
    return True, "Validation passed"

# In run_cpp_simulation():
def run_cpp_simulation(cpp_code: str):
    # Validate before writing
    valid, message = validate_cpp_code(cpp_code)
    if not valid:
        return f"Code validation failed:\n{message}\n\nPlease fix these issues and try again."
    
    # ... rest of existing code ...
```

### 5. **Add Code Template Library**

**Problem**: Agent starts from scratch each time.

**Solution**: Create a template system:

```python
# templates.py
NS3_LTE_HANDOVER_TEMPLATE = """
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/lte-module.h"
#include "ns3/mobility-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("ns3Agent");

int main(int argc, char* argv[])
{{
    // Create helpers
    Ptr<LteHelper> lteHelper = CreateObject<LteHelper>();
    Ptr<PointToPointEpcHelper> epcHelper = CreateObject<PointToPointEpcHelper>();
    lteHelper->SetEpcHelper(epcHelper);
    lteHelper->SetHandoverAlgorithmType("ns3::NoOpHandoverAlgorithm");
    
    // Create nodes
    NodeContainer enbNodes;
    enbNodes.Create(2);
    NodeContainer ueNodes;
    ueNodes.Create(1);
    
    // Setup mobility
    MobilityHelper mobility;
    Ptr<ListPositionAllocator> positionAlloc = CreateObject<ListPositionAllocator>();
    positionAlloc->Add(Vector(0, 0, 0));    // eNB 1
    positionAlloc->Add(Vector(100, 0, 0));  // eNB 2
    positionAlloc->Add(Vector(0, 0, 0));    // UE start
    mobility.SetPositionAllocator(positionAlloc);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(enbNodes);
    
    // UE with velocity
    mobility.SetMobilityModel("ns3::ConstantVelocityMobilityModel");
    mobility.Install(ueNodes);
    Ptr<ConstantVelocityMobilityModel> ueMob = 
        ueNodes.Get(0)->GetObject<ConstantVelocityMobilityModel>();
    ueMob->SetVelocity(Vector(20, 0, 0));
    
    // Install devices
    NetDeviceContainer enbLteDevs = lteHelper->InstallEnbDevice(enbNodes);
    NetDeviceContainer ueLteDevs = lteHelper->InstallUeDevice(ueNodes);
    
    // Install Internet stack on UEs
    InternetStackHelper internet;
    internet.Install(ueNodes);
    Ipv4InterfaceContainer ueIpIfaces = epcHelper->AssignUeIpv4Address(ueLteDevs);
    
    // Attach UE to first eNB
    lteHelper->Attach(ueLteDevs.Get(0), enbLteDevs.Get(0));
    
    // Setup X2
    lteHelper->AddX2Interface(enbNodes);
    
    // Schedule handover
    lteHelper->HandoverRequest(Seconds(1.0), 
                              ueLteDevs.Get(0), 
                              enbLteDevs.Get(0), 
                              enbLteDevs.Get(1));
    
    // {CUSTOM_CODE}
    
    Simulator::Stop(Seconds(5.0));
    Simulator::Run();
    Simulator::Destroy();
    
    return 0;
}}
"""

@tool
def get_ns3_template(template_name: str) -> str:
    """Get a working ns-3 code template by name.
    Available templates: 'lte_handover', 'basic_lte', 'mobility'"""
    templates = {
        "lte_handover": NS3_LTE_HANDOVER_TEMPLATE,
        # Add more templates...
    }
    return templates.get(template_name, "Template not found")
```

### 6. **Improved Observation Parsing**

**Problem**: Agent doesn't extract useful information from errors.

**Solution**: Parse errors intelligently:

```python
def parse_compilation_error(error_text: str) -> dict:
    """Extract actionable information from compilation errors"""
    info = {
        "error_type": None,
        "missing_member": None,
        "suggestion": None
    }
    
    if "no member named" in error_text:
        info["error_type"] = "missing_member"
        # Extract member name
        import re
        match = re.search(r"no member named '(\w+)'", error_text)
        if match:
            info["missing_member"] = match.group(1)
            info["suggestion"] = f"The method {match.group(1)}() doesn't exist in this version. Check examples."
    
    elif "use of undeclared identifier" in error_text:
        info["error_type"] = "undeclared_identifier"
        match = re.search(r"use of undeclared identifier '(\w+)'", error_text)
        if match:
            info["missing_member"] = match.group(1)
            info["suggestion"] = f"Missing #include for {match.group(1)} or wrong type name."
    
    return info

# Modify run_cpp_simulation to use this:
if result.returncode != 0:
    error_info = parse_compilation_error(combined_output)
    return (f"Simulation failed with return code {result.returncode}\n\n"
            f"Error Type: {error_info.get('error_type', 'unknown')}\n"
            f"Suggestion: {error_info.get('suggestion', 'Check syntax')}\n\n"
            f"Full Output:\n{combined_output}")
```

## Implementation Priority

1. **HIGH PRIORITY**: Add `read_ns3_example` tool - This is the biggest gap
2. **HIGH PRIORITY**: Add code validation in ns3_tool.py
3. **MEDIUM**: Improve REASON_SYSTEM_PROMPT with patterns
4. **MEDIUM**: Add template system
5. **LOW**: Enhanced error parsing

## Quick Fix for Current Issue

For the immediate handover simulation, the agent should:

1. Call `read_ns3_example("lena-x2-handover")`
2. Study the structure
3. Adapt it rather than creating from scratch

This would immediately solve 90% of the compilation errors.
