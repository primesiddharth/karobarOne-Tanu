import sys
from pathlib import Path

# Ensure service root and app package are on sys.path for testing
svc_root = Path(__file__).resolve().parent
if str(svc_root) not in sys.path:
    sys.path.insert(0, str(svc_root))
