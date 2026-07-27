"""PyInstaller entry point for KeirstinLink backend.

This file lives at the repo root so PyInstaller can import keirstin_link as a package.
"""
import io
import sys

# PyInstaller --onefile bundles launched without a console may have None or a
# broken stdout/stderr object. Uvicorn's default formatter calls .isatty() on
# stdout, which can crash. Always provide a safe wrapper before uvicorn loads.
class _SafeStream:
    def __init__(self, target):
        self._target = target
    def write(self, s):
        if self._target:
            return self._target.write(s)
    def flush(self):
        if self._target:
            return self._target.flush()
    def isatty(self):
        return False
    def __getattr__(self, name):
        if self._target:
            return getattr(self._target, name)
        return lambda *a, **k: None

if sys.stdout is None or not hasattr(sys.stdout, 'isatty'):
    sys.stdout = _SafeStream(sys.stdout)
if sys.stderr is None or not hasattr(sys.stderr, 'isatty'):
    sys.stderr = _SafeStream(sys.stderr)

from keirstin_link.main import main

if __name__ == "__main__":
    main()
