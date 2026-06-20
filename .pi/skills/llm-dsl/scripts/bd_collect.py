#!/usr/bin/env python3
"""Collect results from completed bd issues in a molecule."""

import sys
import json
import argparse

sys.path.insert(0, '/home/tue/code/ai/llm-dsl')

from src.bd_runner import BdPipelineRunner


def main():
    parser = argparse.ArgumentParser(description="Collect results from a molecule")
    parser.add_argument("--mol-id", "-m", required=True, help="Molecule root issue ID")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print output")
    args = parser.parse_args()

    runner = BdPipelineRunner()
    results = runner.collect_molecule_results(args.mol_id)

    output = []
    for r in results:
        entry = {
            "bd_id": r["bd_id"],
            "status": r.get("status", "?"),
            "parsed_ok": r["parsed_ok"],
        }
        if r["parsed_ok"]:
            entry["artifacts"] = [
                {"path": a.get_attr("path"), "action": a.get_attr("action")}
                for a in r.get("artifacts", [])
            ]
        else:
            entry["error"] = r.get("error", "unknown")
        output.append(entry)

    if args.pretty:
        print(json.dumps(output, indent=2))
    else:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
