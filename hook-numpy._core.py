"""Custom hook to force-collect numpy._core C extensions that PyInstaller's
static analysis misses due to numpy's lazy __getattr__ imports."""
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = collect_submodules("numpy._core")
binaries = collect_dynamic_libs("numpy._core")
