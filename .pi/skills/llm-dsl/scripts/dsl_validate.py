#!/usr/bin/env python3
"""Validate DSL against a schema."""

import sys
import json
import argparse

sys.path.insert(0, '/home/tue/code/ai/llm-dsl')

from src.dsl_parser import parse_dsl, DslParseError


def main():
    parser = argparse.ArgumentParser(description="Validate LLM-DSL")
    parser.add_argument("--file", "-f", help="Read DSL from file")
    parser.add_argument("--schema", "-s", help="Schema name (for error messages)")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    dsl = _extract_dsl(text)
    if not dsl:
        print("Error: No DSL found", file=sys.stderr)
        sys.exit(1)

    try:
        parsed = parse_dsl(dsl)
        print(f"OK: Valid DSL (tag={parsed.tag}, attrs={list(parsed.attrs.keys())})")
    except DslParseError as e:
        schema = args.schema or "unknown"
        print(f"FAIL [{schema}]: {e}", file=sys.stderr)
        sys.exit(1)


def _extract_dsl(text: str) -> str:
    for start_tag in ["[result", "[task"]:
        idx = text.find(start_tag)
        if idx != -1:
            close = "[/" + start_tag[1:] + "]"
            end = text.rfind(close)
            if end != -1:
                return text[idx:end + len(close)]
    return ""


if __name__ == "__main__":
    main()
