---
name: llm-dsl
description: >
  Multi-agent workflow orchestration using LLM-DSL (Domain-Specific Language)
  and bd (beads) issue tracker. Use when decomposing a task into parallel
  subagent work (code, review, test, etc.), collecting results, and generating
  summaries. The agent decomposes NL input into DSL task messages, creates bd
  issues, monitors completion, and synthesizes results.
---

# LLM-DSL Skill

## When to Use

Use this skill when:
- The user asks you to do a task that benefits from parallel subagent work
- You need to decompose a task into code + review + test
- You want structured, machine-readable task/result messages
- You want token-efficient inter-agent communication

## Overview

LLM-DSL uses `bd` (beads) as the workflow engine and DSL (bracket-tag format)
for structured task/result messages:

1. **Decompose** NL input into DSL task messages
2. **Create** bd issues with DSL bodies (uses formula → molecule)
3. **Monitor** progress via `bd ready` / `bd mol progress`
4. **Collect** results from completed issues
5. **Summarize** work completed

## Quick Start

### 1. Check available formulas

```bash
bd formula list
```

### 2. Pour a molecule

```bash
bd mol pour <formula-name> --var key=value
```

### 3. Monitor progress

```bash
bd ready                    # What's ready to work on?
bd mol progress <mol-id>    # Overall progress
bd blocked                   # What's blocked?
```

### 4. Complete a task

```bash
# Update issue body with DSL result
bd update <issue-id> --body-file - << 'DSL'
[result id=<task-id> status=complete]
[artifact type=file path=<path> action=<created|modified|deleted> lines=<N>]
[added fn=<name> in:<type> out:<type>]
[/result]
DSL

# Close the issue
bd close <issue-id>
```

### 5. Collect results

```bash
# Show a completed issue
bd show <issue-id>

# List all issues in a molecule
bd mol show <mol-id>
```

## DSL Format

### Task Message

```
[task id=<id> type=<agent-type>]
[goal]<what to achieve>[/goal]
[file read=<path>]           # Files to read
[spec]...[/spec]             # Structured specification
[context-ref id=<ref>]       # Reference prior task output
[output-artifact path=<path>] # Expected output files
[/task]
```

### Result Message

```
[result id=<id> status=complete|partial|failed|blocked]
[artifact type=file path=<path> action=created|modified|deleted lines=<N>]
[added fn=<name> in:<type> out:<type>]
[removed fn=<name>]
[test-suite total=<N> pass=<N> fail=<N>]
  [test name=<name> status=pass|fail reason=<if-fail>]
[/test-suite]
[verdict approve|request-changes|block]
[finding severity=critical|major|minor|info path=<file>:<line>]
<finding text>
[/finding]
[/result]
```

## Workflow Patterns

### Code + Review + Test (parallel)

```bash
# Pour the code review pipeline formula
bd mol pour code-review-pipeline --var task_description="<description>"

# Steps are created with dependencies:
# implement → review (depends on implement)
# implement → test (depends on implement)

# Complete implement first
bd close <implement-id>  # Review and test auto-unblock

# Then complete review and test
bd close <review-id>
bd close <test-id>

# Molecule auto-closes when all steps done
```

### Iterative Fix Loop

```bash
# Work on implement
bd close <implement-id>

# If review requests changes, create a new fix task
bd create "Fix: <description>" \
  --agent coder \
  --depends-on <review-id> \
  --body-file - << 'DSL'
[task type=code]
[goal]Address review findings[/goal]
[context-ref id=<review-id>.findings]
[/task]
DSL
```

## Common Commands

```bash
# List open issues
bd list

# List by label
bd list --label agent=coder

# Show issue details
bd show <id>

# Update body
bd update <id> --body-file - << 'EOF'
...
EOF

# Close (complete)
bd close <id>

# Reopen
bd reopen <id>

# Add dependency
bd dep add <dependent> --depends-on <blocker>

# Show dependency tree
bd dep tree <id>
```

## Formulas

Available formulas in `.beads/formulas/`:

| Formula | Description | Steps |
|---------|-------------|-------|
| `code-review-pipeline` | Implement + review + test | 3 steps (implement → review + test) |

To create a new formula, add a `.formula.json` file to `.beads/formulas/`:

```json
{
  "formula": "my-pipeline",
  "variables": {"task_description": {"required": true}},
  "steps": [
    {"id": "step1", "title": "Step 1", "agent": "coder"},
    {"id": "step2", "title": "Step 2", "agent": "reviewer", "depends_on": ["step1"]}
  ]
}
```

Then cook it:

```bash
bd cook .beads/formulas/my-pipeline.formula.json --persist
```

## Scripts

Helper scripts in `scripts/`:

```bash
# Parse and validate DSL from stdin
echo '[task id=t1 type=code]...' | python3 scripts/dsl_parse.py

# Validate against schema
python3 scripts/dsl_validate.py --schema code-task --file task.txt
```

## Result Parsing

When reading results from `bd show`, extract the DSL from the body:

```
# The issue body contains natural language + DSL
# Look for [result ...] ... [/result] or [task ...] ... [/task]
# The DSL is the machine-readable structured data
```

To parse programmatically:

```bash
bd show <id> | python3 scripts/dsl_parse.py
```
