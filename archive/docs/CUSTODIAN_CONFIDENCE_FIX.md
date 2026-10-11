# Custodian Premature Confidence Fix

## Problem

The Custodian was setting `confident=True` before actually retrieving code snippets, producing outputs like:

```
confident=True 
final_report="Will include code snippets for mobility installation..."
```

This is a **promise** of future work, not actual gathered information.

## Root Cause

The LLM was interpreting "confident" as "I know what I need to do" rather than "I have already gathered the required information."

## Solution: Three-Layer Defense

### 1. **Enhanced System Prompt** (Explicit Rules)

Added `CRITICAL RULES FOR SETTING confident=True` section:

```python
CRITICAL RULES FOR SETTING confident=True:
1. Your final_report MUST contain ACTUAL C++ CODE SNIPPETS (not promises or descriptions)
2. Code snippets must be ALREADY RETRIEVED from tools (visible in "Recent tool results")
3. Each code snippet must include:
   - The actual C++ code lines
   - Explanation of what it does
   - Why it's relevant to the task
4. DO NOT set confident=True if you're planning to retrieve code "next" - you must HAVE it already
5. If you only have example names, you are NOT confident yet - use read_ns3_example first

If you say "Will include code snippets..." you are NOT confident.
```

### 2. **Improved User Message** (Reminder)

Enhanced the message sent to Custodian with explicit reminders:

```python
"CRITICAL REMINDER:\n"
"- Only set confident=True if your final_report contains ACTUAL C++ CODE that you've ALREADY retrieved\n"
"- Code must be visible in 'Recent tool results' above\n"
"- Do NOT say 'will include' or 'will show' - you must HAVE the code NOW\n"
"- If you only have example names, you need to read_ns3_example first\n"
"- Your final_report should have code like: Ptr<LteHelper> lteHelper = CreateObject<LteHelper>(); etc."
```

### 3. **Post-Response Validation** (Safety Net)

Added validation logic that runs **after** Custodian responds:

```python
if response.confident:
    # Check 1: Has tools been called at all?
    observations = state.get("observations", [])
    if not observations or len(observations) == 0:
        print("[Custodian] WARNING: Claimed confident but hasn't retrieved any information yet!")
        actual_confidence = False  # Override
    
    else:
        final_report = response.final_report or ""
        
        # Check 2: Contains promise words?
        promise_indicators = ["will include", "will show", "will provide", ...]
        has_promises = any(indicator in final_report.lower() for indicator in promise_indicators)
        
        # Check 3: Contains actual C++ code?
        code_indicators = ["::", "Ptr<", "CreateObject", "Install", ...]
        has_code = any(indicator in final_report for indicator in code_indicators)
        
        # Override if promises found OR no code found
        if has_promises or not has_code:
            print("[Custodian] WARNING: Claimed confident but final_report lacks actual code!")
            actual_confidence = False  # Override
```

## Validation Logic

The validation performs three checks:

| Check | Purpose | Action if Failed |
|-------|---------|------------------|
| **Has observations?** | Ensure tools were called | Override `confident=False` |
| **Contains promises?** | Detect "will include" phrases | Override `confident=False` |
| **Contains code?** | Look for C++ patterns like `::`, `Ptr<`, `CreateObject` | Override `confident=False` |

## Example: Before vs After

### Before (Bad)
```
[Custodian] Tool: null, Confident: True
final_report: "Will include code snippets for mobility installation 
(positionAlloc, MobilityHelper settings) and X2 handover setup..."
```
❌ No actual code, just promises

### After (Good - Scenario 1: Override)
```
[Custodian] Tool: read_ns3_example, Confident: False (was True, overridden)
[Custodian] WARNING: Claimed confident but final_report lacks actual code snippets!
[Custodian] Has promises: True, Has code: False
summary: "Need to actually retrieve code snippets, not just plan to do so."
```
✅ System detects and prevents premature confidence

### After (Good - Scenario 2: Proper Confidence)
```
[Custodian] Tool: null, Confident: True
final_report: "Here are the code snippets:

1. Mobility Setup:
```cpp
MobilityHelper mobility;
Ptr<ListPositionAllocator> positionAlloc = CreateObject<ListPositionAllocator>();
positionAlloc->Add(Vector(0.0, 0.0, 0.0));
mobility.SetPositionAllocator(positionAlloc);
mobility.Install(nodes);
```

This shows how to configure mobility..."
```
✅ Has actual code, no promises, properly confident

## Benefits

1. **Prevents False Starts** - Coder won't receive empty guidance
2. **Forces Tool Usage** - Custodian must actually retrieve examples
3. **Self-Correcting** - Validation catches LLM mistakes automatically
4. **Better Logging** - Clear warnings show when overrides happen
5. **Maintains Quality** - Only allows confidence when information is complete

## Testing

To verify the fix works:

```bash
python langgraphagent_optimized.py
```

Watch for:
- `[Custodian] WARNING:` messages indicating overrides
- Custodian making multiple tool calls before being confident
- `final_report` containing actual C++ code snippets when `confident=True`
- No more "will include" or "will provide" in final reports

## Edge Cases Handled

1. **No tool calls yet** → Override to `confident=False`
2. **Only has example names** → Detects lack of code, overrides
3. **Has code but also promises** → Detects "will", overrides  
4. **Empty final_report** → Handled by code check
5. **Only documentation, no code** → Detected by C++ pattern check

## Related Files

- `langgraphagent_optimized.py` - Main implementation with fix
- `CONTEXT_OPTIMIZATION_REPORT.md` - Previous optimizations
