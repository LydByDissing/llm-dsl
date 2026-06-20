"""
BD Pipeline Runner — wraps `bd` CLI commands for multi-agent workflow orchestration.

Agents talk DSL-to-DSL. No static NL translation.
The main agent (LLM) reads DSL results from bd and produces a DSL summary.
"""

from __future__ import annotations
import subprocess
import json
import time
from dataclasses import dataclass, field
from typing import Any

from src.dsl_parser import parse_dsl, DslParseError
# No NL translation needed — agents talk DSL-to-DSL


# ── BD CLI Wrapper ──

def bd_run(*args, input_text: str = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run a `bd` command. Uses --json for structured output."""
    cmd = ["bd", "--json"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, input=input_text)


def bd_create(title: str, body: str, labels: list[str] = None,
              acceptance: list[str] = None, deps: list[str] = None,
              silent: bool = False) -> str | None:
    """Create a bd issue. Returns issue ID or None."""
    args = ["create", title]
    if silent:
        args.append("--silent")
    if labels:
        args.extend(["--labels", ",".join(labels)])
    for acc in (acceptance or []):
        args.extend(["--acceptance", acc])
    if body:
        args.extend(["--body-file", "-"])

    result = bd_run(*args, input_text=body)
    out = result.stdout.strip()

    # Parse JSON output to get ID
    # Find the JSON part (skip any warnings)
    json_start = out.find("{")
    if json_start == -1:
        json_start = out.find("[")
    if json_start != -1:
        try:
            data = json.loads(out[json_start:])
            if isinstance(data, list) and data:
                return data[0].get("id")
            if isinstance(data, dict):
                return data.get("id")
        except json.JSONDecodeError:
            pass

    # Fallback: look for ID in text
    for line in out.split("\n"):
        if "Created issue:" in line:
            parts = line.split("Created issue:")
            if len(parts) > 1:
                issue_id = parts[1].strip().split(" ")[0].strip()
                if "-" in issue_id:  # looks like an ID
                    return issue_id
    return None


def bd_update_body(bd_id: str, body: str):
    """Update an issue's body."""
    bd_run("update", bd_id, "--body-file", "-", input_text=body)


def bd_close(bd_id: str):
    """Close an issue."""
    bd_run("close", bd_id)


def bd_show(bd_id: str) -> dict:
    """Show issue details. Returns dict."""
    result = bd_run("show", bd_id)
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def bd_add_dep(bd_id: str, dep_id: str):
    """Add dependency: bd_id depends on dep_id."""
    bd_run("dep", "add", bd_id, "--depends-on", dep_id)


def bd_ready() -> list[dict]:
    """List issues ready to work on."""
    result = bd_run("ready")
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def bd_set_state(bd_id: str, state: str):
    """Set issue state."""
    bd_run("set-state", bd_id, state)


def bd_list(label: str = None, status: str = None) -> list[dict]:
    """List issues."""
    args = ["list"]
    if label:
        args.extend(["--label", label])
    if status:
        args.extend(["--status", status])
    result = bd_run(*args)
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


# ── BD Pipeline Runner ──

@dataclass
class BdTask:
    task_id: str
    bd_id: str
    agent_type: str
    body: str = ""
    status: str = "open"


class BdPipelineRunner:
    """Orchestrates multi-agent workflows via `bd` CLI."""

    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose

    def log(self, msg: str):
        if self.verbose:
            print(f"  [bd] {msg}")

    def create_task(self, task_id: str, agent_type: str, body: str,
                    labels: list[str] = None,
                    acceptance: list[str] = None,
                    deps: list[str] = None) -> str:
        """Create a task issue. Returns bd issue ID."""
        title = self._extract_title(body, task_id)
        all_labels = [f"agent={agent_type}"]
        if labels:
            all_labels.extend(labels)

        if self.dry_run:
            print(f"  [DRY RUN] create: {title} [{all_labels}]")
            return f"dry-{task_id}"

        bd_id = bd_create(
            title=title,
            body=body,
            labels=all_labels,
            acceptance=acceptance,
        )
        if not bd_id:
            raise RuntimeError(f"Failed to create: {title}")

        self.log(f"Created {bd_id}: {title}")

        if deps:
            for dep in deps:
                bd_add_dep(bd_id, dep)
                self.log(f"  dep: {bd_id} -> {dep}")

        return bd_id

    def _extract_title(self, body: str, fallback: str) -> str:
        """Extract title from DSL body."""
        start = body.find("[goal]")
        if start != -1:
            end = body.find("[/goal]", start)
            if end != -1:
                return body[start + 6:end].strip()[:80]
        # Try first line
        first_line = body.strip().split("\n")[0]
        if len(first_line) < 80:
            return first_line
        return fallback

    def update_result(self, bd_id: str, result_body: str):
        """Update issue with DSL result."""
        if self.dry_run:
            print(f"  [DRY RUN] update {bd_id}")
            return
        bd_update_body(bd_id, result_body)
        self.log(f"Updated {bd_id}")

    def complete_task(self, bd_id: str):
        """Close a task issue."""
        if self.dry_run:
            print(f"  [DRY RUN] close {bd_id}")
            return
        bd_close(bd_id)
        self.log(f"Closed {bd_id}")

    def get_result(self, bd_id: str) -> dict:
        """Get parsed result from an issue. Returns dict with DSL data."""
        info = bd_show(bd_id)
        body = info.get("description", "")

        # Extract [result] DSL from body
        idx = body.find("[result")
        if idx != -1:
            end = body.rfind("[/result]")
            if end != -1:
                dsl = body[idx:end + len("[/result]")]
                try:
                    parsed = parse_dsl(dsl)
                    return {
                        "bd_id": bd_id,
                        "dsl": dsl,
                        "parsed": parsed,
                        "status": parsed.get_attr("status", "unknown"),
                        "artifacts": parsed.children_by_tag("artifact"),
                        "parsed_ok": True,
                    }
                except DslParseError as e:
                    return {"bd_id": bd_id, "dsl": dsl, "parsed_ok": False, "error": str(e)}

        return {"bd_id": bd_id, "dsl": "", "parsed_ok": False, "error": "No [result] found"}

    def collect_results(self, bd_ids: list[str]) -> list[dict]:
        """Collect parsed results from multiple issues."""
        return [self.get_result(bid) for bid in bd_ids]

    def create_summary(self, title: str, summary_body: str) -> str:
        """Create a summary issue. Returns bd issue ID."""
        bd_id = bd_create(
            title=title,
            body=summary_body,
            labels=["agent=main", "type=summary"],
        )
        if bd_id:
            self.log(f"Created summary: {bd_id}")
        return bd_id

    def build_summary_prompt(self, results: list[dict]) -> str:
        """Build a prompt for the main agent to generate a summary.

        Returns a prompt string that the LLM will use to produce
        a short summary of the completed tasks.
        """
        parts = ["## Completed Tasks\n"]

        for r in results:
            if not r.get("parsed_ok"):
                parts.append(f"- {r['bd_id']}: ERROR - {r.get('error', 'unknown')}")
                continue

            parsed = r["parsed"]
            status = parsed.get_attr("status", "?")

            # Brief highlights
            highlights = []

            artifacts = parsed.children_by_tag("artifact")
            if artifacts:
                files = [a.get_attr("path", "?").split("/")[-1] for a in artifacts]
                highlights.append(f"files: {', '.join(files)}")

            added = parsed.children_by_tag("added")
            if added:
                fns = [a.get_attr("fn", "?") for a in added]
                highlights.append(f"added: {', '.join(fns)}")

            verdict = parsed.child("verdict")
            if verdict:
                highlights.append(f"verdict: {verdict.text.strip()}")

            findings = parsed.children_by_tag("finding")
            if findings:
                highlights.append(f"{len(findings)} finding(s)")

            suite = parsed.child("test-suite")
            if suite:
                total = suite.get_attr("total", "?")
                p = suite.get_attr("pass", "?")
                f = suite.get_attr("fail", "?")
                highlights.append(f"tests: {p}/{total} pass, {f} fail")

            parts.append(f"- {r['bd_id']} [{status}]: {', '.join(highlights)}")

        parts.append("\n## Task\n")
        parts.append("Write a short summary (2-3 sentences) of what was accomplished.")
        parts.append("Mention any issues or action items.")

        return "\n".join(parts)
