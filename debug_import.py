import sys
import os
import traceback

print("Current working directory:", os.getcwd())
print("Python version:", sys.version)
print("System path:", sys.path)

try:
    print("\nAttempting to import local_collect_race_data...")
    import local_collect_race_data
    print("Successfully imported local_collect_race_data from:", local_collect_race_data.__file__)
except Exception:
    print("\nImport failed! Traceback:")
    traceback.print_exc()
