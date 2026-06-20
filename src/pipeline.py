"""
Level 3: Full Pipeline Runner with Real LLM Orchestration.

Two modes:
- Direct mode: Calls CLI agents (pi/Claude) directly via subprocess
- BD mode: Creates bd issues, agents pick them up from `bd ready`

In both cases, the main agent (LLM) decomposes NL input into DSL tasks,
and subagents (LLMs) produce DSL results.
"""

from __future__ import annotations
import subprocess
import json
import tiktoken
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

from src.dsl_parser import parse_dsl, DslParseError
from src.dsl_serializer import serialize_dsl
from src.translator import dsl_to_nl, aggregate_results
from src.process_loader import load_process, ProcessDefinition


# ── Data Structures ──

@dataclass
class PipelineMessage:
    msg_id: str
    from_agent: str
    to_agent: str
    raw_text: str          # Raw LLM output
    dsl_text: str          # Extracted DSL
    parsed: Any = None     # Parsed DslNode
    tokens: int = 0


@dataclass
class PipelineResult:
    nl_output: str
    messages: list[PipelineMessage] = field(default_factory=list)
    total_tokens: int = 0
    dsl_tokens: int = 0
    nl_tokens: int = 0
    success: bool = False
    errors: list[str] = field(default_factory=list)


# ── CLI Agent Interface ──

def call_agent(system_prompt: str, user_prompt: str,
               agent: str = "pi", model: str = "",
               timeout: int = 120) -> tuple[str, bool]:
    """Call a CLI agent in non-interactive mode."""
    if agent == "claude":
        cmd = ["claude", "--print", "--output-format", "text",
               "--append-system-prompt", system_prompt]
        if model:
            cmd.extend(["--model", model])
    elif agent == "pi":
        cmd = ["pi", "--print",
               "--append-system-prompt", system_prompt]
        if model:
            cmd.extend(["--model", model])
    else:
        return f"Unknown agent: {agent}", False

    cmd.append(user_prompt)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else "(no stderr)"
            return f"CLI error (exit {result.returncode}): {stderr}", False
        return result.stdout.strip(), True
    except subprocess.TimeoutExpired:
        return f"CLI timeout (>{timeout}s)", False
    except FileNotFoundError:
        return f"{agent} CLI not found", False


def count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


# ── Prompt Construction ──

def build_main_agent_prompt(process: ProcessDefinition) -> str:
    """Build the main agent's system prompt.

    The main agent needs:
    1. DSL schema reference (how to produce valid DSL)
    2. Process definition (agents, schemas, composition)
    3. Instructions for NL→DSL decomposition
    4. Instructions for DSL→NL aggregation
    """
    # Build agent descriptions
    agent_descs = []
    for aid, adef in process.agents.items():
        if adef.role == "orchestrator":
            continue
        schemas_in = ", ".join(adef.input_schemas)
        schemas_out = ", ".join(adef.output_schemas)
        agent_descs.append(
            f"  - {adef.label} ({aid}): {adef.description}\n"
            f"    Input schema: {schemas_in}\n"
            f"    Output schema: {schemas_out}"
        )

    # Build schema reference
    schema_refs = []
    for sname, sdef in process.schemas.items():
        fields = []
        for fname, fdef in sdef.fields.items():
            attrs = ", ".join(f"{k}:{v}" for k, v in fdef.attrs.items())
            fields.append(f"      [{fname} {attrs}]")
        schema_refs.append(
            f"  {sname}:\n" + "\n".join(fields)
        )

    agents_block = "\n".join(agent_descs)
    schemas_block = "\n".join(schema_refs)

    return f"""## ROLE: Main Orchestrator Agent

You orchestrate multi-agent workflows. You speak to the user in natural language
and communicate with subagents in LLM-DSL format.

### DSL FORMAT
[tagname key=value]content[/tagname]
- Single line, no whitespace between tags
- Leaf tags (no body): [tagname attr=value]
- Text content: [tagname]text here[/tagname]

### AVAILABLE SUBAGENTS
{agents_block}

### DSL SCHEMAS
{schemas_block}

### YOUR WORKFLOW

**Phase 1 — Decompose:**
When you receive a user request, break it into tasks. For each task, determine
which subagent should handle it. Then produce a [task] message for each.

**Phase 2 — Dispatch:**
Output each [task] message. The system will route them to the appropriate subagents.

**Phase 3 — Aggregate:**
When you receive [result] messages from all subagents, synthesize them into a
coherent natural language response for the user. Mention what each subagent did,
any issues found, and what needs attention.

### TASK MESSAGE FORMAT
[task id=<unique-id> type=<agent-type>]
[goal]<what to achieve in natural language>[/goal]
[file read=<path>]  (files the subagent should read)
[spec]...[/spec]  (structured spec, if applicable)
[context-ref id=<other-task.artifacts>]  (reference prior results)
[output-artifact path=<path>]  (expected output files)
[/task]

### RESPONSE FORMAT
Respond with ONLY the DSL [task] messages, one per subagent.
Do NOT include explanations or natural language.

Example:
[task id=t1 type=code]
[goal]Add input validation to POST /users endpoint[/goal]
[file read=src/handlers/user.py]
[spec]
[field name=email required=true rule=format:email]
[field name=name required=true rule=length:max=100]
[/spec]
[output-artifact path=src/handlers/user.py]
[/task]
"""


def build_subagent_prompt(process: ProcessDefinition, agent_id: str) -> str:
    """Build a subagent's system prompt.

    The subagent needs:
    1. Its role description
    2. DSL schema reference for its input/output
    3. Instructions to respond in DSL format
    """
    adef = process.agents[agent_id]

    # Get input schema details
    input_schemas = []
    for sname in adef.input_schemas:
        if sname in process.schemas:
            sdef = process.schemas[sname]
            fields = []
            for fname, fdef in sdef.fields.items():
                attrs = ", ".join(f"{k}:{v}" for k, v in fdef.attrs.items())
                fields.append(f"    [{fname} {attrs}]")
            input_schemas.append(f"  {sname}:\n" + "\n".join(fields))

    # Get output schema details
    output_schemas = []
    for sname in adef.output_schemas:
        if sname in process.schemas:
            sdef = process.schemas[sname]
            fields = []
            for fname, fdef in sdef.fields.items():
                attrs = ", ".join(f"{k}:{v}" for k, v in fdef.attrs.items())
                fields.append(f"    [{fname} {attrs}]")
            output_schemas.append(f"  {sname}:\n" + "\n".join(fields))

    input_block = "\n".join(input_schemas) if input_schemas else "  (see core schema)"
    output_block = "\n".join(output_schemas) if output_schemas else "  (see core schema)"

    return f"""## ROLE: {adef.label}

{adef.description}

### DSL FORMAT
[tagname key=value]content[/tagname]
- Single line, no whitespace between tags
- Leaf tags (no body): [tagname attr=value]
- Text content: [tagname]text here[/tagname]

### INPUT SCHEMA (what you receive)
{input_block}

### OUTPUT SCHEMA (what you produce)
{output_block}

### RESPONSE FORMAT
Respond with ONLY a DSL [result] message. Do NOT include natural language.

[result id=<task-id> status=complete|partial|failed|blocked]
[artifact type=file path=<path> action=created|modified|deleted lines=<N>]
[added fn=<name> in:<type> out:<type>]
[removed fn=<name>]
[test-suite total=<N> pass=<N> fail=<N>]
  [test name=<name> status=pass|fail reason=<if-fail>]
[/test-suite]
[verdict approve|request-changes|block]
[finding severity=critical|major|minor|info path=<file>:<line>]
<finding text here>
[/finding]
[complexity delta=<+Ncyclomatic>]
[/result]
"""


# ── DSL Extraction ──

def extract_dsl(text: str, start_tag: str = "[result") -> str:
    """Extract DSL from LLM output. Handles markdown fences and extra text."""
    t = text.strip()

    # Remove markdown code fences
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
        t = t.strip()

    # Find the start tag
    idx = t.find(start_tag)
    if idx == -1:
        return t  # Return as-is for error reporting

    # Find the matching close tag
    close_tag = "[/" + start_tag[1:]  # [result -> [/result
    end_idx = t.rfind(close_tag)
    if end_idx == -1:
        return t[idx:]

    return t[idx:end_idx + len(close_tag)]


# ── Pipeline Runner ──

def run_pipeline(process_path: str, user_input: str,
                 agent: str = "pi", model: str = "",
                 verbose: bool = False) -> PipelineResult:
    """Run the full multi-agent pipeline with real LLM calls.

    Args:
        process_path: Path to process.yaml
        user_input: Natural language input from user
        agent: CLI agent to use ("pi" or "claude")
        model: Model name (optional)
        verbose: Print intermediate outputs

    Returns:
        PipelineResult with NL output, messages, and token counts
    """
    result = PipelineResult(nl_output="")

    # Load process definition
    try:
        process = load_process(process_path)
    except Exception as e:
        result.errors.append(f"Failed to load process: {e}")
        return result

    main_agent = None
    for aid, adef in process.agents.items():
        if adef.role == "orchestrator":
            main_agent = adef
            break

    if not main_agent:
        result.errors.append("No orchestrator agent defined")
        return result

    # ── Phase 1: Main Agent decomposes user input into DSL tasks ──
    if verbose:
        print("=" * 60)
        print("PHASE 1: Main Agent — NL to DSL decomposition")
        print("=" * 60)

    main_prompt = build_main_agent_prompt(process)

    if verbose:
        print(f"\nSystem prompt ({count_tokens(main_prompt)} tokens):")
        print(main_prompt[:300] + "...")
        print(f"\nUser input: {user_input}")

    raw_output, success = call_agent(
        main_prompt, user_input, agent=agent, model=model
    )

    if not success:
        result.errors.append(f"Main agent LLM call failed: {raw_output}")
        return result

    if verbose:
        print(f"\nMain agent output:\n{raw_output[:500]}")

    # Parse task messages from main agent output
    task_messages = _extract_tasks(raw_output)

    if not task_messages:
        result.errors.append("Main agent did not produce any [task] messages")
        result.errors.append(f"Raw output: {raw_output[:300]}")
        return result

    if verbose:
        print(f"\nExtracted {len(task_messages)} task(s):")
        for tid, ttext in task_messages.items():
            print(f"  {tid}: {ttext[:100]}...")

    # Record main agent messages
    for tid, ttext in task_messages.items():
        try:
            parsed = parse_dsl(ttext)
        except DslParseError as e:
            result.errors.append(f"Task {tid} failed to parse: {e}")
            parsed = None

        msg = PipelineMessage(
            msg_id=tid,
            from_agent="main",
            to_agent=parsed.get_attr("type", "unknown") if parsed else "unknown",
            raw_text=ttext,
            dsl_text=ttext,
            parsed=parsed,
            tokens=count_tokens(ttext),
        )
        result.messages.append(msg)
        result.dsl_tokens += msg.tokens

    # ── Phase 2: Dispatch tasks to subagents ──
    if verbose:
        print("\n" + "=" * 60)
        print("PHASE 2: Subagent execution")
        print("=" * 60)

    subagent_results: dict[str, str] = {}  # task_id -> DSL result

    for tid, ttext in task_messages.items():
        parsed = parse_dsl(ttext)
        agent_type = parsed.get_attr("type", "")
        task_goal = parsed.child("goal")
        goal_text = task_goal.text.strip() if task_goal else ""

        # Find the agent for this task type
        target_agent = None
        for aid, adef in process.agents.items():
            if adef.role == "worker" and agent_type in adef.input_schemas:
                target_agent = aid
                break

        if not target_agent:
            # Fallback: match by schema name containing the type
            for aid, adef in process.agents.items():
                if adef.role == "worker":
                    for sname in adef.input_schemas:
                        if agent_type in sname:
                            target_agent = aid
                            break
                if target_agent:
                    break

        if not target_agent:
            result.errors.append(f"No agent found for task type: {agent_type}")
            continue

        if verbose:
            print(f"\nTask {tid} -> {target_agent} (type={agent_type})")
            print(f"  Goal: {goal_text[:80]}...")

        # Build subagent prompt
        sub_prompt = build_subagent_prompt(process, target_agent)

        # The subagent receives the task message as its user input
        sub_output, success = call_agent(
            sub_prompt, ttext, agent=agent, model=model
        )

        if not success:
            result.errors.append(f"Subagent {target_agent} failed: {sub_output}")
            continue

        # Extract DSL from subagent output
        dsl_result = extract_dsl(sub_output, "[result")

        if verbose:
            print(f"  Subagent output:\n{dsl_result[:300]}")

        # Validate the result
        try:
            result_parsed = parse_dsl(dsl_result)
            if verbose:
                print(f"  Parsed OK: status={result_parsed.get_attr('status', '?')}")
        except DslParseError as e:
            result.errors.append(f"Subagent {target_agent} result failed to parse: {e}")
            if verbose:
                print(f"  Parse error: {e}")
            result_parsed = None

        subagent_results[tid] = dsl_result

        msg = PipelineMessage(
            msg_id=f"{tid}-result",
            from_agent=target_agent,
            to_agent="main",
            raw_text=sub_output,
            dsl_text=dsl_result,
            parsed=result_parsed,
            tokens=count_tokens(dsl_result),
        )
        result.messages.append(msg)
        result.dsl_tokens += msg.tokens

    # ── Phase 3: Main Agent aggregates results → NL ──
    if verbose:
        print("\n" + "=" * 60)
        print("PHASE 3: Aggregation — DSL to NL")
        print("=" * 60)

    # Build aggregation prompt for main agent
    results_text = "\n\n".join(
        f"Result from {r.from_agent} ({r.msg_id}):\n{r.dsl_text}"
        for r in result.messages
        if r.to_agent == "main"
    )

    aggregation_prompt = f"""## ROLE: Main Orchestrator Agent (Aggregation Phase)

You have received results from subagents in LLM-DSL format.
Synthesize them into a coherent natural language response for the user.

### SUBAGENT RESULTS

{results_text}

### YOUR TASK
Write a natural language summary for the user covering:
1. What each subagent did
2. Key findings, issues, or concerns
3. Files changed
4. Any action items needing user attention

Be concise but informative. Use bullet points or sections for clarity.
"""

    nl_output, success = call_agent(
        aggregation_prompt,
        "Please synthesize the subagent results into a user-facing summary.",
        agent=agent,
        model=model,
    )

    if not success:
        result.errors.append(f"Aggregation LLM call failed: {nl_output}")
        # Fallback: use static translator
        per_agent = {}
        for r in result.messages:
            if r.to_agent == "main" and r.parsed:
                agent_type = r.parsed.get_attr("type", "coder")
                per_agent[agent_type] = r.dsl_text
        nl_output = aggregate_results(per_agent)
        result.errors.append("Fell back to static aggregation")

    result.nl_output = nl_output
    result.nl_tokens = count_tokens(nl_output)
    result.total_tokens = result.dsl_tokens + result.nl_tokens
    result.success = len([m for m in result.messages if m.to_agent == "main"]) > 0

    if verbose:
        print(f"\nNL Output ({result.nl_tokens} tokens):\n{nl_output}")

    return result


def _extract_tasks(text: str) -> dict[str, str]:
    """Extract [task] messages from main agent output.

    Returns dict of task_id -> task_dsl_text.
    """
    tasks = {}
    t = text.strip()

    # Remove markdown fences
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:-1]) if len(lines) > 2 else t
        t = t.strip()

    # Find all [task ...]...[/task] blocks
    idx = 0
    while True:
        start = t.find("[task ", idx)
        if start == -1:
            break

        # Find the matching [/task]
        end_tag = "[/task]"
        end = t.find(end_tag, start)
        if end == -1:
            break

        task_text = t[start:end + len(end_tag)]

        # Extract task ID
        id_match = task_text.split("id=", 1)
        if len(id_match) > 1:
            task_id = id_match[1].split(" ")[0].split("]")[0]
            tasks[task_id] = task_text

        idx = end + len(end_tag)

    return tasks
