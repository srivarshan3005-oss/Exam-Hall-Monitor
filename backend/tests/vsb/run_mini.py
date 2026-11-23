"""Tiny pytest-free runner so the pure-Python parser tests can run in environments without pytest installed."""
import importlib, inspect, sys, traceback
def run(modname):
    mod = importlib.import_module(modname); ok = bad = 0
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("test_") and not inspect.signature(fn).parameters:
            try: fn(); ok += 1
            except Exception: bad += 1; print("FAIL", modname, name); traceback.print_exc()
    print(f"{modname}: {ok} passed, {bad} failed"); return bad
if __name__ == "__main__":
    sys.exit(1 if sum(run(m) for m in sys.argv[1:]) else 0)
