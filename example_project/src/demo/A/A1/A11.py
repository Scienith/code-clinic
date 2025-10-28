# Module A11 - No stub functions (fully implemented)
import json
from datetime import datetime
from demo.common import get_base_config

def calculate_metrics(data):
    """Calculate various metrics from the data."""
    if not data:
        return {}
    
    total_items = len(data)
    numeric_values = [item.get('value', 0) for item in data if isinstance(item.get('value'), (int, float))]
    
    metrics = {
        'total_items': total_items,
        'average_value': sum(numeric_values) / len(numeric_values) if numeric_values else 0,
        'max_value': max(numeric_values) if numeric_values else 0,
        'min_value': min(numeric_values) if numeric_values else 0,
        'timestamp': datetime.now().isoformat()
    }
    
    return metrics

def generate_report(metrics):
    """Generate a formatted report from metrics."""
    if not metrics:
        return "No metrics available"
    
    report_lines = [
        "=== Data Analysis Report ===",
        f"Generated at: {metrics.get('timestamp', 'Unknown')}",
        f"Total items processed: {metrics.get('total_items', 0)}",
        f"Average value: {metrics.get('average_value', 0):.2f}",
        f"Value range: {metrics.get('min_value', 0)} - {metrics.get('max_value', 0)}",
        "==========================="
    ]
    
    return "\n".join(report_lines)

def validate_metrics(metrics):
    """Validate that metrics contain required fields."""
    required_fields = ['total_items', 'average_value', 'timestamp']
    return all(field in metrics for field in required_fields)

def save_metrics_to_file(metrics, filename):
    """Save metrics to a JSON file."""
    try:
        with open(filename, 'w') as f:
            json.dump(metrics, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving metrics: {e}")
        return False

class MetricsCalculator:
    """Advanced metrics calculation utilities."""
    
    def __init__(self):
        self.history = []
    
    def add_calculation(self, data):
        """Add a calculation to history."""
        metrics = calculate_metrics(data)
        self.history.append(metrics)
        return metrics
    
    def get_historical_average(self, field):
        """Get historical average for a specific field."""
        values = [h.get(field, 0) for h in self.history if field in h]
        return sum(values) / len(values) if values else 0
    
    def clear_history(self):
        """Clear calculation history."""
        self.history.clear()
