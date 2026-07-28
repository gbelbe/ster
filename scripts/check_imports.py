from __future__ import annotations

import sys

# stdlib_module_names is available in Python 3.10+; project requires 3.11+
stdlib = set(sys.stdlib_module_names)

# Add some common ones that might be missed or are built-into the interpreter
stdlib.update(sys.builtin_module_names)

core_deps = {
    "rdflib",
    "typer",
    "rich",
    "textual",
    "idna",
    "fastapi",
    "watchfiles",
    "pylode",
    "llm",
    "httpx",
    "yaml",  # pyyaml
    "msgpack",
    "pydantic_settings",
    "starlette",
    "multipart",  # python-multipart
    "pydantic",
    "uvicorn",
    "shellingham",  # added common ones likely covered by extras
}


def is_third_party(module_name):
    if module_name.startswith("."):
        return False
    base = module_name.split(".")[0]
    return base != "ster" and base not in stdlib


imports = set()
lines = sys.stdin.readlines()
for line in lines:
    line = line.strip()
    if not line:
        continue
    if line.startswith("import "):
        # Parse everything after "import "
        modules_str = line[len("import ") :].strip()
        # Handle multiple modules: import os, sys
        for m in modules_str.split(","):
            m = m.strip()
            if not m:
                continue
            # Handle aliases: import module as alias
            actual_module = m.split(" as ")[0].strip()
            # Take the first part in case of any trailing noise
            imports.add(actual_module.split()[0])
    elif line.startswith("from "):
        parts = line.split()
        if len(parts) > 1:
            # Handle: from module import ...
            # We only care about the module being imported from
            actual_module = parts[1].strip()
            # Handle aliases: from . import module as alias
            # (though is_third_party handles leading dots)
            imports.add(actual_module)

third_party_imports = {m.split(".")[0] for m in imports if is_third_party(m)}
missing = third_party_imports - core_deps

print("Third-party imports found:")
for m in sorted(third_party_imports):
    print(f"  {m}")

print("\nPotentially missing from core dependencies:")
for m in sorted(missing):
    # Some might be in optional dependencies or sub-packages of others
    print(f"  {m}")
