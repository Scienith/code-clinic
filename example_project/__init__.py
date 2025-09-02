# Example project for demonstrating CodeXray capabilities
"""
This is an example project with a hierarchical package structure
designed to test CodeXray's dependency analysis and stub detection.
"""
from example_project.A import main_workflow, analyze_results, DataProcessor

def run_example():
    """Run the example workflow to demonstrate the package functionality."""
    sample_data = {'id': 'example', 'value': 42, 'timestamp': '2024-01-01T00:00:00'}
    
    processor = DataProcessor()
    result = main_workflow(sample_data)
    analysis = analyze_results(result) if result else {}
    
    return {
        'processed_data': result,
        'analysis': analysis
    }

# Expose main components at package level
__all__ = ['main_workflow', 'analyze_results', 'DataProcessor', 'run_example']