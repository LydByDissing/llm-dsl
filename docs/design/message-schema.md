# Message Schema Format Design

## Goals

- Compact: minimal syntax overhead, low token cost
- Unambiguous: every construct has one meaning
- Composable: messages nest, reference each other, aggregate
- Deterministic: same data → same serialization
- Parsable: simple grammar, no ambiguity for LLMs
- Schema-first: validated against declared schemas, unknown fields pass through

## Non-Goals

- Human-writeable DSL syntax (the LLM produces it, code parses it)
- Full programming language features (no expressions, loops, variables)
- Lossy compression (no information loss vs equivalent NL)

---

## 1. Syntax Form

The DSL uses a **bracket-tag form** inspired by BBCode/SXML:

```
[tag-name attr1=val1 attr2=val2 ...]content[/tag-name]
```

Attributes use bare `key=value` syntax. Values with spaces use `:key="value"` form.

This form is chosen because:
- LLMs already handle bracket/tag syntax well (HTML, XML, BBCode are in training data)
- It's more compact than JSON/XML for the semantic content we encode
- Attributes compress named fields without keys-as-tokens overhead

---

## 2. Type System

### 2.1 Primitive Types

| Type | Syntax | Examples |
|------|--------|----------|
| `str` | bare text or quoted | `hello`, `"hello world"` |
| `int` | bare integer | `42`, `-1`, `0` |
| `float` | decimal number | `3.14`, `-0.5` |
| `bool` | `true` / `false` | `true`, `false` |
| `path` | colon-separated | `src/handler.py:42`, `src/models/user.py` |
| `id` | alphanumeric identifier | `t1`, `task-42`, `a3f2dd` |
| `enum` | bare keyword from a set | `pass`, `fail`, `approve`, `modified` |

### 2.2 Composite Types

```
# List (repeated tags or comma-separated)
[field name=email]
[field name=name]
# OR
field=[email, name]

# Map (repeated key=value)
[meta key=severity value=minor]
[meta key=category value=security]
```

### 2.3 Reference Type

References use a dedicated `ref` attribute that points to a message ID and optionally a sub-path:

```
ref=<message-id>                # reference entire message
ref=<message-id>.<field>        # reference a specific top-level field
ref=<message-id>.<field>.<sub>  # reference into nested content
ref=<message-id>.artifacts       # shorthand for all artifacts in a result
```

References are **resolved at consumption time**, not inlined. This is the primary mechanism for avoiding data re-transmission.

---

## 3. Core Schema (Built-In)

These types are always available and do not need declaration.

### 3.1 `[task]` — Work assignment from orchestrator to subagent

```
[task id=<id> type=<enum>]
  [goal]<natural language goal>[/goal]
  [importance <float 0-1>]
  [deadline <relative time>]     # e.g. "within 3 turns"
[/task]
```

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `id` | `id` | yes | Unique task identifier for referencing |
| `type` | `enum` | yes | Task type (agent-type specific, e.g. `code`, `review`, `test`) |

**Child tags:** agent-type specific (see domain schemas below). Common children:

| Tag | Type | Description |
|-----|------|-------------|
| `[req]` | req ref | Requirement being implemented (required) |
| `[goal]` | text (str) | What to achieve, in NL |
| `[file]` | file ref | File to read/modify |
| `[spec]` | structured | Structured specification |
| `[output-artifact]` | file ref | Expected output files |
| `[context-ref]` | reference | References prior message data |
| `[focus]` | key-value | What aspects to focus on |
| `[test-cases]` | list of cases | Test case descriptions |
| `[importance]` | float | Priority weight |

### 3.2 `[result]` — Work completion from subagent to orchestrator

```
[result id=<id> status=<enum>]
  ...
[/result]
```

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `id` | `id` | yes | Matches the `[task id=...]` this responds to |
| `status` | `enum` | yes | `complete`, `partial`, `failed`, `blocked` |

**Common child tags:**

| Tag | Type | Description |
|-----|------|-------------|
| `[artifact]` | structured | Produced/modified files |
| `[verdict]` | enum | `approve`, `request-changes`, `block` |
| `[finding]` | structured | Issues found |
| `[test-suite]` | structured | Test results |
| `[added]` | structured | Things added |
| `[removed]` | structured | Things removed |
| `[error]` | structured | Error details if status=failed |
| `[note]` | text (str) | Free-form notes |

### 3.3 `[artifact]` — Produced or modified file

```
[artifact type=file path=<path> action=<enum> lines=<int>]
```

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `type` | `enum` | yes | `file`, `config`, `schema` |
| `path` | `path` | yes | File path, optionally with `:line` |
| `action` | `enum` | yes | `created`, `modified`, `deleted` |
| `lines` | `int` | no | Lines added (with `+`/`-` prefix) or total |
| `hash` | `str` | no | Content hash for integrity |

### 3.4 `[context-ref]` — Reference to prior message data

```
[context-ref id=<ref>]
```

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `id` | `ref` | yes | Reference to message and optionally a sub-path |

The consumer resolves this reference and loads the referenced data into working context before processing the task. The data is **not** serialized into the message.

### 3.5 `[req]` — Requirement reference

```
[req id=<req-id>]
```

Links the task to the requirement it implements. Required on every `[task]`. Use `id=orphan` when no requirement can be identified — this triggers orphan reporting in the synthesis step.

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `id` | `str` | yes | Requirement ID (e.g. `REQ-42`), or `orphan` |

The `req=` label on the bd issue mirrors this field and enables `bd list --label req=REQ-42` queries for REQ status rollup.

### 3.6 `[file]` — File to read

```
[file read=<path>]content[/file]
[file read=<path>]
```

With inline content or just a reference. The consumer can choose to inline or reference based on size.

### 3.7 `[added]` / `[removed]` — Structural change record

```
[added fn=<name> in:<type> out:<type>]
[removed fn=<name>]
```

Records what was added or removed from the codebase. More compact than diffs, more structured than prose.

**Attributes:**
| Attr | Type | Required | Description |
|------|------|----------|-------------|
| `fn` | `str` | yes | Function/type/class name |
| `in` | `str` | no | Input type signature |
| `out` | `str` | no | Output type signature |
| `path` | `path` | no | Where it lives |

---

## 4. Domain Schemas (Agent-Type Specific)

Domain schemas extend the core with agent-specific fields. They are declared in the process definition (see `agent-process.md`).

### 4.1 Code Task Schema

Used by `type=code` tasks:

```
[task id=<id> type=code]
  [goal]...[/goal]
  [spec]
    [field name=<str> required=<bool> rule=<str>]
    [field name=<str> required=<bool> type=<str> rule=<str>]
    [on-invalid status=<int> format=<str>]
  [/spec]
  [file read=<path>]
  [output-artifact path=<path>]
[/task]
```

**`[field]` attributes:** `name`, `required`, `type`, `rule`

**`[spec]`** — Structured specification of what to implement. Domain-specific interpretation.

**`[on-invalid]`** — Error handling specification.

### 4.2 Review Task/Result Schema

Used by `type=review` tasks and results:

```
[task id=<id> type=review]
  [goal]...[/goal]
  [context-ref id=<ref>]
  [focus security=<bool> style=<bool> correctness=<bool>]
[/task]

[result id=<id> status=complete]
  [verdict approve|request-changes|block]
  [finding severity=<enum> path=<path>:<int>]
    free-form text
  [/finding]
  [security-check status=<enum>]
    [note]...[/note]
  [/security-check]
  [style status=<enum>]
[/result]
```

**`[finding]` attributes:** `severity` (enum: `critical`, `major`, `minor`, `info`), `path` (with line)

**Note: `[security-check]` is a schema-drift example** — it's not in the core schema, and the main agent must passthrough it without understanding it.

### 4.3 Test Task/Result Schema

Used by `type=test` tasks and results:

```
[task id=<id> type=test]
  [goal]...[/goal]
  [context-ref id=<ref>]
  [test-cases]
    [case]...[/case]
  [/test-cases]
  [output-artifact path=<path>]
[/task]

[result id=<id> status=complete]
  [artifact ...]
  [test-suite total=<int> pass=<int> fail=<int>]
    [test name=<str> status=<enum> reason=<str>]
  [/test-suite]
[/result]
```

**`[case]`** — Free-form test case description.

**`[test]` attributes:** `name`, `status` (enum: `pass`, `fail`, `skip`, `error`), `reason` (required if status=fail)

**`[test-suite]` attributes:** `total`, `pass`, `fail`

---

## 5. Reference Protocol

### 5.1 Reference Syntax

```
id=<message-id>                    # entire message
id=<message-id>.<field>            # top-level field/child
id=<message-id>.<field>.<index>    # indexed into a list
id=<message-id>.artifacts          # all [artifact] children
```

### 5.2 Reference Lifecycle

1. **Created**: When a message is produced, its `id` becomes a valid reference target.
2. **Valid**: The referenced message exists in the current conversation/process context.
3. **Resolved**: The consumer loads the referenced data before processing. If the reference is stale (message not found), the consumer emits an `[error]` and the main agent decides retry/escalate.

### 5.3 Forward References

References to messages not yet produced are **not allowed** in the PoC. All references must point to already-delivered messages. This simplifies ordering and eliminates deadlock scenarios.

---

## 6. Serialization Rules (Determinism)

For deterministic output:

1. **Attributes are sorted alphabetically** within each tag.
2. **Children appear in schema-defined order** (core fields first, then domain fields, then unknown fields).
3. **No pretty-printing**: no indentation, no newlines between tags. Single-line serialization.
4. **Enum values are lowercase**.
5. **Empty/omitted attributes are not serialized**.
6. **Text content is stripped of leading/trailing whitespace** within `[tag]...[/tag]`.

### Example: Compact (wire) Form

```
[task id=t1 type=code][goal]Add input validation to POST /users endpoint[/goal][file read=src/handlers/user.py][spec][field name=email required=true rule=format:email][field name=name required=true rule=length:max=100][/spec][/task]
```

### Example: Pretty (debug/display) Form

```
[task id=t1 type=code]
  [goal]Add input validation to POST /users endpoint[/goal]
  [file read=src/handlers/user.py]
  [spec]
    [field name=email required=true rule=format:email]
    [field name=name required=true rule=length:max=100]
  [/spec]
[/task]
```

**Wire form is what agents send. Pretty form is what appears in logs/debug output.**

---

## 7. Schema Validation

### 7.1 Strictness Modes

| Mode | Unknown fields | Missing required | Type mismatch |
|------|---------------|-----------------|---------------|
| `strict` | reject | reject | reject |
| `permissive` | preserve (passthrough) | reject | coerce if safe |
| `open` | preserve | warn only | coerce |

The default is `permissive` for the PoC. Unknown fields are preserved — this is the schema drift mechanism.

### 7.2 Validation Levels

Validation is applied at two levels:

1. **Core validation**: all messages checked against core schema (task, result, artifact, context-ref, file, etc.)
2. **Domain validation**: task/result checked against the declared domain schema for the agent type

A message passes if it validates at core level. Domain validation failures are flagged but don't reject the message — they trigger the passthrough behavior.

---

## 8. Complete Annotated Example

Full message flow from the validation testcase with schema annotations:

### M1: Task dispatch (code)

```
[task id=t1 type=code]                               ← core: task
  [goal]Add input validation to POST /users endpoint[/goal]  ← core: goal (text)
  [file read=src/handlers/user.py]                    ← core: file (read ref)
  [spec]                                              ← domain: code spec
    [field name=email required=true rule=format:email] ← domain: field
    [field name=name required=true rule=length:max=100]
    [field name=age required=false type=int rule=range:0-150]
    [on-invalid status=422 format=standard-error]    ← domain: error config
  [/spec]
  [output-artifact path=src/handlers/user.py]         ← domain: expected output
  [output-artifact path=src/validation/user_schema.py]
[/task]
```

### M4: Result (code)

```
[result id=t1 status=complete]                        ← core: result
  [artifact type=file path=src/handlers/user.py       ← core: artifact
            action=modified lines=+23]
  [artifact type=file path=src/validation/user_schema.py
            action=created lines=18]
  [added fn=validate_user_input in:RequestBody        ← core: added
        out:ValidationResult]
  [test id=manual status=pass]                       ← domain: coder test
  [complexity delta=+2cyclomatic]                    ← domain: complexity metric
[/result]
```

### M5: Result (review) — with schema drift

```
[result id=t2 status=complete]
  [verdict approve]                                   ← domain: review
  [finding severity=minor path=src/handlers/user.py:34] ← domain: review
    Email regex does not support international domains.
    Consider using a library like email-validator.
  [/finding]
  [security-check status=pass]                        ← UNKNOWN (passthrough!)
    [note]SQL injection not applicable — uses ORM[/note]
  [/security-check]
  [style status=pass]                                 ← domain: review
[/result]
```

The `[security-check]` tag is **not in the core schema** and **not in the declared review schema**. Under `permissive` mode, it is preserved as-is and passed through to the main agent. The main agent doesn't need to understand it — it just relays it to the NL expansion step.

---

## 9. Design Decisions & Rationale

### Why bracket-tag form instead of JSON?

| Criterion | Bracket-tag | JSON |
|-----------|------------|------|
| Token efficiency | Higher — no quotes on keys, no commas, no braces | Lower — structural overhead per field |
| LLM familiarity | High — HTML/BBCode in training data | High — JSON everywhere |
| Parsing complexity | Simple regex/state machine | Standard libraries |
| Readability (debug) | Good with pretty-print | Good natively |
| Nested structure | Natural | Natural |

For our use case, bracket-tag wins on token efficiency because we avoid quoting every key name. In a message with 20 attributes, that's ~40 tokens saved (20 keys × 2 quote chars each, which often tokenize as separate tokens).

### Why not YAML?

YAML's significant whitespace is fragile for LLM generation. LLMs frequently mess up indentation. Bracket tags are self-delimiting.

### Why not S-expression / Lisp syntax?

Less familiar to most LLMs. Bracket tags have broader training coverage.

### Why alphabetical attribute ordering?

Determinism. Without a canonical ordering, the same data could serialize differently across invocations, breaking the determinism acceptance criterion.

### Why no expressions or computation?

The DSL is a **data format**, not a language. No need for arithmetic, string operations, or conditionals. Keep it simple, keep it parseable, keep it deterministic.
