# Architecture

The supported package is derived from `archive/prototypes/agens-3.py`, the implementation associated with the attached agens-3 paper. Its specialist roles are separate graph nodes, with the Manager deciding the next assignment.

| Component | Responsibility | Output |
| --- | --- | --- |
| Manager | Decide the next specialist and provide instructions | Structured routing decision |
| Custodian | Retrieve PDF context and read local ns-3 examples | Documentation summary or final report |
| Coder | Generate a full ns-3 simulation | Code and language |
| Execution node | Invoke a selected retrieval or simulation tool | Raw tool output |
| Evaluator | Compare the generated code and output with the prompt | Review and evaluation |
| Finalizer | Summarize observations for the user | Final answer |

The Manager routes to the Custodian, Coder, Evaluator, or Finalizer. Custodian retrieval loops through the execution node until it returns a report. A confident Custodian does not execute another retrieval tool. The Coder passes code through execution to the Evaluator, which returns feedback to the Manager. A final answer terminates the graph.

`create_workflow()` builds the graph explicitly. Importing the package does not initialize Chroma, create API clients, or download a graph diagram. The function accepts injected model clients and collections for offline tests.

Structured responses use Pydantic schemas. `AgentState` carries the initial question, decisions, observations, generated code, evaluation, and visited nodes. Model refusals or missing structured responses fail with an explicit error. The inherited loop limits bound planning and retrieval; they do not guarantee successful simulations.

## Retrieval

PDF pages are split into overlapping chunks and persisted in Chroma with source and page metadata. Search returns up to three passages. Local source tools find examples under `src/*/examples`, `examples`, and `scratch` in the configured simulator installation. This implementation uses a flat PDF collection; it does not claim a separately indexed hierarchy of tutorials, APIs, and code examples.

## Execution

C++ code is written to a unique `scratch/agens3_<id>.cc` target and executed with the ns-3 launcher. Python code uses the active interpreter and requires ns-3 Python bindings in that environment. Both use `NS3_DIR` as the working directory and respect `NS3_TIMEOUT`. Output includes exit status and unfiltered stdout/stderr. Compiler failures therefore remain available to the Evaluator.

Completed CLI workflows save the final graph state as JSON and the latest C++ code separately. Generated files stay outside version control. Agent evaluation is qualitative and should be paired with independent checks of simulation assumptions and outputs.

## Historical implementations

The archive includes the earlier Streamlit interface, alternate agent designs, and development notes. These describe earlier experiments and may differ from this supported workflow. The original source files were preserved during restructuring, including existing local edits.
