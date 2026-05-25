"""Tool schemas, implementations, and metadata extraction.

All external access must go through these registered tools.
The observed_tool_call wrapper in executor.py calls call_tool() here.
"""

import ast
import hashlib
import json
import operator
from urllib.parse import urlparse

import tiktoken
import yaml

# ── OpenAI function-calling schemas ─────────────────────────────────────────

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current or external information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}

CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Perform arithmetic calculations on a mathematical expression.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate, e.g. '(120 - 100) / 100 * 100'",
                },
            },
            "required": ["expression"],
        },
    },
}

_SCHEMAS: dict[str, dict] = {
    "web_search": WEB_SEARCH_SCHEMA,
    "calculator": CALCULATOR_SCHEMA,
}

# ── Config helpers ───────────────────────────────────────────────────────────

def load_config(config_path: str = "config/agent_config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_enabled_tools(config: dict) -> list[str]:
    return [t["name"] for t in config.get("tools", []) if t.get("enabled", True)]


def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    return [_SCHEMAS[n] for n in tool_names if n in _SCHEMAS]


# ── Token counting and hashing ───────────────────────────────────────────────

def _get_encoding(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_schema_tokens(schemas: list[dict], model: str) -> int:
    enc = _get_encoding(model)
    return len(enc.encode(json.dumps(schemas)))


def count_text_tokens(text: str, model: str) -> int:
    enc = _get_encoding(model)
    return len(enc.encode(text))


def compute_tool_registry_hash(schemas: list[dict]) -> str:
    canonical = json.dumps(schemas, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def compute_system_prompt_hash(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:16]


# ── Tool implementations ─────────────────────────────────────────────────────

def _web_search(arguments: dict) -> dict:
    query = arguments["query"]
    max_results = int(arguments.get("max_results", 5))
    try:
        from duckduckgo_search import DDGS
        raw = DDGS().text(query, max_results=max_results)
        results = [
            {"title": r["title"], "url": r["href"], "snippet": r["body"]}
            for r in (raw or [])
        ]
    except Exception as exc:
        results = []
        return {"query": query, "results": results, "error": str(exc)}
    return {"query": query, "results": results}


# Safe AST-based arithmetic evaluator (no eval() on arbitrary code)
_SAFE_OPS: dict = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](
            _safe_eval_node(node.left), _safe_eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval_node(node.operand))
    raise ValueError(f"Unsupported expression node: {ast.dump(node)}")


def _calculator(arguments: dict) -> dict:
    expression = arguments["expression"]
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval_node(tree)
        return {"expression": expression, "result": result, "success": True}
    except Exception as exc:
        return {"expression": expression, "error": str(exc), "success": False}


_IMPLEMENTATIONS: dict[str, callable] = {
    "web_search": _web_search,
    "calculator": _calculator,
}


def call_tool(tool_name: str, arguments: dict) -> dict:
    if tool_name not in _IMPLEMENTATIONS:
        raise ValueError(f"Unknown tool: {tool_name!r}")
    return _IMPLEMENTATIONS[tool_name](arguments)


# ── Source metadata extraction ───────────────────────────────────────────────

def extract_tool_metadata(tool_name: str, result: dict) -> dict:
    """Extract source URL and traceability metadata from a tool result."""
    if tool_name == "web_search":
        urls = [r["url"] for r in result.get("results", []) if r.get("url")]
        domains = sorted({urlparse(u).netloc for u in urls if u})
        status = "full" if urls else ("partial" if not result.get("error") else "none")
        return {
            "source_urls_returned": urls,
            "source_urls_inserted": urls,
            "source_domains": domains,
            "source_traceability_status": status,
        }
    # calculator and any other local tools have no external sources
    return {
        "source_urls_returned": [],
        "source_urls_inserted": [],
        "source_domains": [],
        "source_traceability_status": "full",
    }
