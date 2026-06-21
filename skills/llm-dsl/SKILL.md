---
name: llm-dsl
description: >
  Default orchestration skill for any non-trivial task in this project. Main
  agent plans, scopes, confirms with user, creates bd issues, then spawns a
  haiku conductor-execute sub-agent to run the worker loop. Workers (haiku or
  sonnet) do the actual code/review/test work, tracked via bd issues and
  communicated in compact LLM-DSL. Use for ANY task that produces output: code
  changes, file analysis, research, review, testing. Skip ONLY for pure Q&A or
  one-line factual answers.
---

# LLM-DSL Skill

## Conductor Output Rules (Strict)

- **Steps 1-3: NO user-facing text.** Do not narrate, summarize, or explain. Produce only the Step 4 block.
- **Step 4:** confirm block in the exact fixed format below. Nothing before or after it.
- **Step 5:** one status line only: "Spawning executor (run=<id>)..."
- **Step 6:** structured synthesis report only. No padding, no preamble.

---

## Mandatory Workflow (all six steps, in order)

```
1. UNDERSTAND      — (silent) describe the problem in project context
2. SCOPE           — (silent) state what is in and out of scope
3. PLAN            — (silent) decompose into tasks, each with acceptance criteria; define DoD
4. CONFIRM         — (fixed format) present 1-3 to user, ask "shall I proceed?", WAIT for go-ahead
5. EXECUTE         — create bd issues, spawn conductor-execute
6. SYNTHESIZE      — verify against DoD, report to user
```

**Never skip or reorder steps. Never start step 5 without explicit user approval.**

The main agent handles Steps 1-5. Step 5 spawns a conductor-execute sub-agent (haiku) that drives the worker loop: spawn workers in dependency order, collect results, return synthesis DSL. Main agent reads synthesis DSL and reports to user (Step 6).

---

## Steps 1-3 — Silent Planning

1. **Understand**: what problem, which files/layer, what exists, any ambiguities — ask before assuming
2. **Scope**: explicit in/out bullet lists; boundary is binding on sub-agents
3. **Plan**: decompose into coder/reviewer/tester; each task needs goal, inputs, artifacts, acceptance criteria; define DoD

---

## Step 4 — Confirm (hard gate)

Present steps 1-3 to the user:

```
## Understanding
<1-2 sentences>

## Scope
In: ...
Out: ...

## Plan
Task 1 — <role>: <goal>
  Acceptance: <criteria>
Task 2 — <role>: <goal>
  Acceptance: <criteria>
...

## Definition of Done
<sentence>

Shall I proceed?
```

**Stop. Do not continue until user approves. On changes, re-confirm before proceeding.**

---

## Step 5 — Execute

Only reached after explicit user approval.

### Create bd issues

```bash
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")
BD_ROLE=$(bd create "Action: title" --silent \
  --labels "agent=role,run=$RUN_ID" \
  --acceptance "criterion" \
  --body-file - << DSL_END
[task id=t1 type=code|review|test]
[goal]objective[/goal]
[out path]
[/task]
DSL_END
)
# For reviewer/tester add: --deps "$BD_PRIOR"
```

### Spawn conductor-execute

After creating bd issues, build the exec block and spawn the conductor-execute sub-agent:

```python
EXEC_BLOCK = """
[exec run={RUN_ID}]
[job id={BD_CODER} role=coder model=haiku]
[job id={BD_REVIEWER} role=reviewer model=sonnet depends={BD_CODER}]
[job id={BD_TESTER} role=tester model=haiku depends={BD_CODER}]
[/exec]
"""

Agent(model="haiku", description="Conductor-execute",
      prompt=<conductor_execute_prompt(EXEC_BLOCK, CLAUDE_PROJECT_DIR)>,
      run_in_background=False)
```

### Conductor-execute prompt template

Conductor-execute prompt: read $CLAUDE_PLUGIN_ROOT/skills/llm-dsl/prompts/conductor-execute.md

Worker prompt template: read $CLAUDE_PLUGIN_ROOT/skills/llm-dsl/prompts/worker.md

### Crash recovery

```bash
bd list --label "run=$RUN_ID" --status open   # find stalled issues
# Re-spawn the Agent with the same bd_id — sub-agent re-reads and resumes
```

---

## Step 6 — Synthesize

Read synthesis DSL from conductor-execute. Check each job's bd issue. Verify DoD: all acceptance criteria pass, no critical/major reviewer findings, no test failures. Report to user: files changed, test counts, review verdict, DoD met/unmet, action items.

---

## Model Selection Framework

### Default model assignment

| Role | Default model |
|------|--------------|
| coder | haiku |
| reviewer | sonnet |
| tester | haiku |

### Escalation rules (main agent decides at Step 3)

**Escalate coder to sonnet when:**
- Multi-file refactor touching >3 files
- auth / payments / security-critical code
- New module or architectural boundary

**Escalate reviewer to opus when:**
- auth, payments, or data migration changes
- Public API surface changes

Model is encoded in the `[exec]` block `[job model=...]` attribute. Conductor-execute reads and applies it — no heuristics in the executor.

---

## Code Style for Sub-Agents

Sub-agents generating code MUST follow these rules. No exceptions.

### Naming

- Functions: `snake_case`, abbreviated but inferrable (`val_email` not `validate_email_address`)
- Classes: `PascalCase`, abbreviated (`EmailVal` not `EmailValidator`)
- Local variables: Go-style short (`n`, `r`, `buf`, `err`, `ok`, `fn`, `val`, `idx`)

### Comments and docs

- No docstrings. Ever.
- No inline comments.
- Type hints on public functions only. Not on private helpers, not on local variables.

### Formatting

- No blank lines between class methods.
- Single blank line between top-level functions.
- f-strings only for string interpolation.
- MUST use list/dict comprehensions instead of explicit loops for single-line operations.
- Use `...` not `pass` in stubs or abstract methods.
- Imports: no blank lines between import groups (stdlib, third-party, local all contiguous).

---

## DSL Format Reference

### Task (main agent → worker)

```
[task id=<id> type=code|review|test]
[goal]<objective>[/goal]
[file read=<path>]           # file to read (multiple allowed)
[spec]...[/spec]             # structured constraints
[ref <prior-task>.artifacts] # reference prior output
[out <path>]                 # expected output file
[/task]
```

### Result (worker → main agent)

```
[result id=<id> s=ok|partial|fail|blocked]
[artifact path=<path> a=new|mod|del n=<lines>]
[added fn=<name> in:<type> out:<type>]
[removed fn=<name>]
[suite t=<total> p=<pass> f=<fail>]
  [test name=<name> s=pass|fail reason=<text>]
[/suite]
[verdict approve|request-changes|block]
[note sev=crit|major|minor|info at=<file>:<line>]<text>[/note]
[/result]
```

### Exec (main agent → conductor-execute)

```
[exec run=<run_id>]
[job id=<bd_id> role=coder|reviewer|tester model=haiku|sonnet|opus]
[job id=<bd_id> role=reviewer model=sonnet depends=<bd_id>]
[/exec]
```

### Synthesis (conductor-execute → main agent)

```
[synthesis run=<run_id> s=ok|partial|fail]
[job id=<bd_id> role=<role> s=ok|fail]
[/synthesis]
```

**Attribute quick-ref:**

| Abbrev | Meaning |
|--------|---------|
| `s=` | status: `ok` / `fail` / `blocked` / `partial` |
| `a=` | file action: `new` / `mod` / `del` |
| `n=` | line count |
| `t=` `p=` `f=` | suite total / pass / fail |
| `sev=` | severity: `crit` / `major` / `minor` / `info` |
| `at=` | file:line location |

---

## Common bd Commands

```bash
bd show <id>                                 # Read issue + body + acceptance criteria
bd list --label agent=coder                  # Filter by role
bd list --label "run=$RUN_ID" --status open  # Find stalled issues
bd ready                                     # Unblocked issues
bd blocked                                   # Blocked issues
bd dep add <child> --depends-on <parent>
bd close <id>
```

