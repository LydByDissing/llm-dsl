#!/usr/bin/env python3
"""Parse DSL from stdin or file and output structured JSON."""

import sys
import json
import argparse

# Add src to path
sys.path.insert(0, '/home/tue/code/ai/llm-dsl')

from src.dsl_parser import parse_dsl, DslParseError


def main():
    parser = argparse.ArgumentParser(description="Parse LLM-DSL from stdin or file")
    parser.add_argument("--file", "-f", help="Read DSL from file instead of stdin")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print output")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    # Extract DSL from text (handles mixed NL + DSL)
    dsl = _extract_dsl(text)
    if not dsl:
        print("Error: No DSL found in input", file=sys.stderr)
        sys.exit(1)

    try:
        parsed = parse_dsl(dsl)
        result = parsed.to_dict()
        if args.pretty:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result))
    except DslParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        sys.exit(1)


def _extract_dsl(text: str) -> str:
    """Extract DSL bracket-tag content from mixed text."""
    # Look for [result or [task
    for start_tag in ["[result", "[task"]:
        idx = text.find(start_tag)
        if idx != -1:
            # close tag: [/<tagname>]
            close = "[/" + start_tag[1:] + "]"
            end = text.rfind(close)
            if end != -1:
                return text[idx:end + len(close)]
    return ""


if __name__ == "__main__":
    main()
