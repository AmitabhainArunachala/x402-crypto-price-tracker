"""Probe the x402 Python SDK to find correct import paths."""
import importlib
import pkgutil

# 1. Check top-level x402 package
import x402
print("=== x402 top-level ===")
print([x for x in dir(x402) if not x.startswith('_')])

# 2. Find all submodules
print("\n=== x402 submodules ===")
for importer, modname, ispkg in pkgutil.walk_packages(x402.__path__, prefix='x402.'):
    print(f"  {modname} {'(pkg)' if ispkg else ''}")

# 3. Try key imports
print("\n=== Trying imports ===")
imports_to_try = [
    "x402.http",
    "x402.http.middleware",
    "x402.http.middleware.fastapi",
    "x402.server",
    "x402.mechanisms",
    "x402.mechanisms.evm",
    "x402.mechanisms.evm.exact",
    "x402.schemas",
    "x402.http.types",
]
for mod in imports_to_try:
    try:
        importlib.import_module(mod)
        print(f"  OK: {mod}")
    except Exception as e:
        print(f"  FAIL: {mod} -> {e}")

# 4. Inspect key modules
print("\n=== x402.http members ===")
try:
    from x402 import http as x402http
    print([x for x in dir(x402http) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\n=== x402.server members ===")
try:
    from x402 import server as x402server
    print([x for x in dir(x402server) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\n=== x402.http.middleware.fastapi members ===")
try:
    from x402.http.middleware import fastapi as x402fastapi
    print([x for x in dir(x402fastapi) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\n=== x402.mechanisms.evm.exact members ===")
try:
    from x402.mechanisms.evm import exact as evmexact
    print([x for x in dir(evmexact) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\n=== x402.http.types members ===")
try:
    from x402.http import types as httptypes
    print([x for x in dir(httptypes) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\n=== x402.schemas members ===")
try:
    from x402 import schemas
    print([x for x in dir(schemas) if not x.startswith('_')])
except Exception as e:
    print(f"Error: {e}")

print("\nDONE")