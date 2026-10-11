from langchain.tools import tool
import glob
import os

@tool
def read_ns3_example(example_name: str) -> str:
    """Read an ns-3 example file by name. This is CRITICAL for understanding correct API usage.
    
    Input: example name without extension (e.g., 'lena-x2-handover', 'lena-simple-epc')
    
    Use this tool when:
    - Documentation mentions an example program
    - You need to see how to properly use ns-3 APIs
    - Compilation errors suggest wrong API usage
    - You're implementing a similar scenario
    
    Examples:
    - read_ns3_example("lena-x2-handover") - for handover examples
    - read_ns3_example("lena-simple-epc") - for basic LTE/EPC setup
    """
    base_path = "/Users/kemalyagizdaskiran/Desktop/ns-3.46.1"
    
    # Search patterns for different example locations
    patterns = [
        f"{base_path}/src/lte/examples/{example_name}.cc",
        f"{base_path}/src/*/examples/{example_name}.cc",
        f"{base_path}/examples/**/{example_name}.cc",
        f"{base_path}/scratch/{example_name}.cc",
    ]
    
    for pattern in patterns:
        files = glob.glob(pattern, recursive=True)
        if files:
            try:
                with open(files[0], 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Return a summary + full code
                    line_count = content.count('\n')
                    return f"Found: {files[0]}\nLines: {line_count}\n\n{content}"
            except Exception as e:
                return f"Error reading {files[0]}: {str(e)}"
    
    # If not found, try to list available examples
    available = []
    for pattern in [f"{base_path}/src/lte/examples/*.cc"]:
        for file in glob.glob(pattern):
            available.append(os.path.basename(file).replace('.cc', ''))
    
    suggestion = f"\nAvailable LTE examples: {', '.join(available[:10])}" if available else ""
    return f"Example '{example_name}' not found.{suggestion}"


@tool
def list_ns3_examples(module: str = "lte") -> str:
    """List available ns-3 example programs for a specific module.
    
    Input: module name (e.g., 'lte', 'wifi', 'mobility', 'applications')
    
    Use this to discover what examples exist before reading them.
    """
    base_path = "/Users/kemalyagizdaskiran/Desktop/ns-3.46.1"
    
    patterns = [
        f"{base_path}/src/{module}/examples/*.cc",
        f"{base_path}/examples/{module}/*.cc",
    ]
    
    examples = []
    for pattern in patterns:
        for file in glob.glob(pattern):
            name = os.path.basename(file).replace('.cc', '')
            examples.append(name)
    
    if examples:
        return f"Available {module} examples ({len(examples)}):\n" + "\n".join(f"  - {ex}" for ex in sorted(examples))
    else:
        return f"No examples found for module '{module}'"


if __name__ == "__main__":
    # Test the tools
    print("=== LISTING LTE EXAMPLES ===")
    print(list_ns3_examples.run("lte"))
    print(read_ns3_example.run("lena-x2-handover"))
