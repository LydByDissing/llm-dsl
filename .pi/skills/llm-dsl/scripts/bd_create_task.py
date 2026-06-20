#!/usr/bin/env python3
"""Create a bd issue with DSL body."""

import sys
import argparse

sys.path.insert(0, '/home/tue/code/ai/llm-dsl')

from src.bd_runner import bd_create


def main():
    parser = argparse.ArgumentParser(description="Create a bd issue with DSL body")
    parser.add_argument("--title", "-t", required=True, help="Issue title")
    parser.add_argument("--body", "-b", help="DSL body (or read from stdin)")
    parser.add_argument("--body-file", "-f", help="Read body from file")
    parser.add_argument("--agent", "-a", help="Agent label (e.g. coder, reviewer)")
    parser.add_argument("--schema", "-s", help="Schema label (e.g. code-task)")
    parser.add_argument("--depends-on", "-d", nargs="+", help="Dependency issue IDs")
    parser.add_argument("--acceptance", "-acc", nargs="+", help="Acceptance criteria")
    args = parser.parse_args()

    # Read body
    if args.body_file:
        with open(args.body_file) as f:
            body = f.read()
    elif args.body:
        body = args.body
    else:
        body = sys.stdin.read()

    # Build labels
    labels = []
    if args.agent:
        labels.append(f"agent={args.agent}")
    if args.schema:
        labels.append(f"schema={args.schema}")

    bd_id = bd_create(
        title=args.title,
        body=body,
        labels=labels or None,
        acceptance=args.acceptance,
        deps=args.depends_on,
    )

    if bd_id:
        print(bd_id)
    else:
        print("Failed to create issue", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
