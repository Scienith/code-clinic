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

from .api import analyze_project
from .stub import stub

__all__ = ["analyze_project", "stub", "__version__"]
__version__ = "0.1.0"
