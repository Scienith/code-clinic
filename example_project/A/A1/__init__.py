# Package A1 - depends on A11 and A12 and common
from example_project.A.A1.A11 import calculate_metrics, generate_report
from example_project.A.A1.A12 import fetch_data, store_results
from example_project.common import validate_permissions, log_activity

def process_data(data):
    """Process raw data using various components."""
    metrics = calculate_metrics(data)
    report = generate_report(metrics)
    return report

def handle_batch(batch_data):
    """Handle a batch of data items."""
    results = []
    for item in batch_data:
        processed = process_single_item(item)
        results.append(processed)
    store_results(results)
    return results

def process_single_item(item):
    """Process a single data item."""
    # Fetch additional data if needed
    extra_data = fetch_data(item.get('id'))
    item['extra'] = extra_data
    return item

class DataManager:
    """Manages data operations."""
    
    def __init__(self):
        self.data_store = []
    
    def add_data(self, data):
        """Add data to the store."""
        self.data_store.append(data)
        return len(self.data_store)
    
    def get_all_data(self):
        """Retrieve all stored data."""
        return self.data_store.copy()
    
    def clear_data(self):
        """Clear all stored data."""
        self.data_store.clear()