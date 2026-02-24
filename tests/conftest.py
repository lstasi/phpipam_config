import sys
import os

# Add the scripts directory to the path so we can import the sync module
scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
sys.path.insert(0, scripts_dir)
