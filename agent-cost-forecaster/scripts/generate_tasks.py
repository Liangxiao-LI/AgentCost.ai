"""Standalone script: expand seed_templates.yaml into seed_tasks.jsonl.

Usage (from agent-cost-forecaster/ directory):
    python scripts/generate_tasks.py
    python scripts/generate_tasks.py --n 5 --output data/seed_tasks.jsonl

Prefer using the CLI alias instead:
    acf generate-tasks --n 3
"""

import json
import random
import sys
from pathlib import Path

import yaml


def generate(templates_path: str, output_path: str, n_per_template: int) -> None:
    with open(templates_path) as f:
        data = yaml.safe_load(f)

    variables: dict = data.get("variables", {})
    tasks: list[dict] = []

    for category_name, category_data in data.items():
        if category_name == "variables" or not isinstance(category_data, dict):
            continue
        target_tools: list = category_data.get("target_tools", [])
        templates: list = category_data.get("templates", [])

        for template in templates:
            for _ in range(n_per_template):
                prompt = template
                for var_name, values in variables.items():
                    placeholder = f"{{{var_name}}}"
                    if placeholder in prompt:
                        prompt = prompt.replace(placeholder, str(random.choice(values)))
                tasks.append({
                    "prompt": prompt,
                    "category": category_name,
                    "target_tools": target_tools,
                    "generation_strategy": "template",
                })

    random.shuffle(tasks)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    print(f"Generated {len(tasks)} tasks → {output_path}")
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    for cat, count in sorted(counts.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate seed tasks from templates")
    parser.add_argument("--templates", default="data/seed_templates.yaml")
    parser.add_argument("--output", default="data/seed_tasks.jsonl")
    parser.add_argument("--n", type=int, default=3, help="Expansions per template")
    args = parser.parse_args()
    generate(args.templates, args.output, args.n)
