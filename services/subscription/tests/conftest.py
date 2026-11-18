# tests/conftest.py
import os
import sys
svc_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if svc_dir not in sys.path:
    sys.path.insert(0, svc_dir)
