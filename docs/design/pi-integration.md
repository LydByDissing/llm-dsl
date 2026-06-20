# Pi CLI Integration Design

## Goal

Make the LLM-DSL pipeline usable from `pi` CLI as the primary agent harness.
The agent should be able to:
1. Create and manage multi-agent workflows via `bd` + DSL
2. Decompose NL tasks into DSL task messages
3. Dispatch to subagents and collect results
4. Generate summaries from completed work

## Approach: Skill + Scripts

We need two things:

1. **A skill** (`.pi/skills/llm-dsl/SKILL.md`) — tells pi how to use the pipeline
2. **Helper scripts** (`.pi/skills/llm-dsl/scripts/`) — Python tools callable from the skill

We do NOT need a TypeScript extension. The skill + scripts approach is simpler
and sufficient for our use case.

## Skill Structure

```
.pi/skills/llm-dsl/
├── SKILL.md              # Skill instructions
└── scripts/
    ├── dsl_parse.py      # Parse DSL from text
    ├── dsl_validate.py   # Validate DSL against schema
    ├── bd_create_task.py # Create a bd issue with DSL body
    ├── bd_collect.py     # Collect results from completed issues
    └── bd_summary.py     # Generate summary from results
```

## How It Works

### Agent invokes the skill

When the user asks the agent to do a multi-agent task, pi loads the skill:

```
User: "Add input validation to the POST /users endpoint"
→ pi reads SKILL.md
→ Agent decomposes into DSL tasks
→ Agent creates bd issues with DSL bodies
→ Subagents (or agent itself) do the work
→ Agent collects results and summarizes
```

### Skill content (SKILL.md)

The skill tells the agent:
- What LLM-DSL is and when to use it
- How to decompose NL into DSL task messages
- How to create bd issues with DSL bodies
- How to collect results from completed issues
- How to generate summaries

### Scripts

The scripts wrap our Python tools for command-line use:

```bash
# Parse DSL from text
python3 scripts/dsl_parse.py '[result id=t1 status=complete]...'

# Validate DSL against schema
python3 scripts/dsl_validate.py --schema code-task '[task ...]'

# Create a bd issue with DSL body
python3 scripts/bd_create_task.py \
  --title "Implement: Add validation" \
  --agent coder \
  --body '[task id=t1 type=code]...' \
  --acceptance "Code implements validation"

# Collect results from completed issues
python3 scripts/bd_collect.py --mol-id llm-dsl-mol-xxx

# Generate summary
python3 scripts/bd_summary.py --results results.json
```

## What We Need to Build

### 1. Skill file

`.pi/skills/llm-dsl/SKILL.md` — the skill instructions

### 2. CLI wrapper scripts

Thin wrappers around `src/dsl_parser.py`, `src/bd_runner.py` etc.
that can be called from the command line.

### 3. Main agent prompt

A prompt template that tells the main agent how to orchestrate:
- Read user NL input
- Decompose into DSL tasks
- Create bd issues
- Monitor progress
- Collect and summarize

## Testing the Integration

```bash
# Install the skill
cp -r .pi/skills/llm-dsl ~/.pi/agent/skills/

# Test from pi
pi -p "Use the llm-dsl skill to create a code review pipeline for adding input validation"
```

## Design Decisions

### Why a skill, not an extension?

- Skills are simpler (markdown + scripts vs TypeScript)
- Skills are portable across agent harnesses (Claude Code, Codex, etc.)
- Skills use progressive disclosure (description in system prompt, full instructions on-demand)
- No need for custom tools or event interception

### Why scripts, not direct Python calls?

- Skills instruct the agent to run shell commands
- Scripts are the natural interface between the skill and our Python code
- Scripts can be tested independently
- Scripts work with any agent harness, not just pi

### Why not a prompt template?

A prompt template could work but:
- Skills are more discoverable (listed in system prompt)
- Skills support progressive disclosure
- Skills can include scripts and references
- Skills are the standard pi mechanism for this
