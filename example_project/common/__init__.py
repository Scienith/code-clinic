# Common utilities package
"""
This package contains common utilities used across the project.
It provides base classes, configuration, and shared functionality.
"""
from codeclinic import stub

def get_base_config():
    """Get base configuration settings."""
    return {
        'version': '1.0.0',
        'debug': False,
        'max_retries': 3
    }

class BaseProcessor:
    """Base processor class that other processors inherit from."""
    
    def __init__(self, config=None):
        self.config = config or get_base_config()
    
    def validate_input(self, data):
        """Validate input data - to be overridden by subclasses."""
        if not data:
            raise ValueError("Input data cannot be empty")
        return True
    
    @stub
    def process(self, data):
        """Process data - abstract method."""
        pass
    
    @stub 
    def cleanup(self):
        """Cleanup resources - abstract method."""
        pass

def setup_logging():
    """Setup logging configuration."""
    import logging
    logging.basicConfig(level=logging.INFO)
    return logging.getLogger(__name__)

# Stub functions for demonstration
@stub
def authenticate_user(credentials):
    """Authenticate user with given credentials."""
    pass

@stub
def validate_permissions(user, action):
    """Validate if user has permission for action.""" 
    pass

@stub
def log_activity(user, action, result):
    """Log user activity."""
    pass
