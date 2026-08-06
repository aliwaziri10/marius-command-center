"""
CODEMAP.json generator.

Walks every .py file in the repo (skipping common noise dirs), uses the
standard library `ast` module (no external dependencies) to extract:
  - every function/method definition: file, name, line, args, docstring-first-line
  - call relationships: which named functions each function calls
  - every Supabase/PostgREST table name referenced (patterns like
    f"{SUPABASE_URL}/rest/v1/<table>" or "/rest/v1/<table>")
  - every env var read via os.environ["X"], os.environ.get("X"), os.getenv("X")

Writes a single CODEMAP.json at the repo root. Designed to run inside a
GitHub Actions workflow with zero pip installs required.
"""

import ast
import json
import os
import re
import sys

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".github", "venv", ".venv"}

TABLE_PATTERN = re.compile(r"/rest/v1/([A-Za-z_][A-Za-z0-9_]*)")


def find_py_files(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                yield os.path.join(dirpath, fname)


def get_docstring_first_line(node):
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    return doc.strip().split("\n")[0][:150]


class CallCollector(ast.NodeVisitor):
    """Collects the names of functions called within a single function body."""

    def __init__(self):
        self.calls = []

    def visit_Call(self, node):
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name:
            self.calls.append(name)
        self.generic_visit(node)


def extract_env_vars(source_text):
    env_vars = set()
    for m in re.finditer(r'os\.environ\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']\s*\]', source_text):
        env_vars.add(m.group(1))
    for m in re.finditer(r'os\.environ\.get\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']', source_text):
        env_vars.add(m.group(1))
    for m in re.finditer(r'os\.getenv\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']', source_text):
        env_vars.add(m.group(1))
    return sorted(env_vars)


def extract_tables(source_text):
    return sorted(set(TABLE_PATTERN.findall(source_text)))


def process_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()

    functions = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return {
            "path": path,
            "parse_error": str(e),
            "functions": [],
            "env_vars": [],
            "tables": [],
        }

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            collector = CallCollector()
            collector.visit(node)
            args = [a.arg for a in node.args.args]
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": args,
                "calls": sorted(set(collector.calls)),
                "docstring": get_docstring_first_line(node),
            })

    return {
        "path": path,
        "functions": functions,
        "env_vars": extract_env_vars(source),
        "tables": extract_tables(source),
    }


def build_codemap(root="."):
    files = []
    all_env_vars = set()
    all_tables = set()

    for path in sorted(find_py_files(root)):
        rel = os.path.relpath(path, root)
        result = process_file(path)
        result["path"] = rel
        files.append(result)
        all_env_vars.update(result.get("env_vars", []))
        all_tables.update(result.get("tables", []))

    return {
        "generated_by": "generate_codemap.py",
        "file_count": len(files),
        "env_vars": sorted(all_env_vars),
        "tables": sorted(all_tables),
        "files": files,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    codemap = build_codemap(root)
    out_path = os.path.join(root, "CODEMAP.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(codemap, f, indent=2)
    print(f"Wrote {out_path}: {codemap['file_count']} files, "
          f"{len(codemap['env_vars'])} env vars, {len(codemap['tables'])} tables")


if __name__ == "__main__":
    main()
