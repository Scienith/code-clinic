"""
CodeClinic - Diagnose your Python project: import graph + stub maturity metrics

Simple API for analyzing Python projects:

    from codeclinic import analyze_project, stub

    # Analyze project (with visualization)
    result = analyze_project("my_project", output="analysis", format="svg")
    print(f"Stub ratio: {result['summary']['stub_ratio']:.1%}")

    # Analyze project (stats only)
    result = analyze_project("my_project")
    modules = result['modules']

    # Use @stub decorator to mark incomplete functions
    @stub
    def my_function():
        pass
"""


def analyze_project(*args, **kwargs):
    """Lazy import wrapper for analyze_project to avoid heavy imports at package import time."""
    from .api import analyze_project as _analyze_project

    return _analyze_project(*args, **kwargs)


from .stub import stub

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:
    # Python < 3.8 compatibility
    from importlib_metadata import PackageNotFoundError, version

try:
    __version__ = version("codeclinic")
except PackageNotFoundError:
    # Fallback for development/uninstalled package
    __version__ = "unknown"

__all__ = ["analyze_project", "stub", "__version__"]
