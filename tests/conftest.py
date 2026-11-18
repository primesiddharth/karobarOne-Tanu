# microservice/tests/conftest.py
import os
import sys

microservice_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if microservice_dir not in sys.path:
    sys.path.insert(0, microservice_dir)
