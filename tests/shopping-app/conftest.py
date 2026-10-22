import importlib.util
import os
import sys
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

root_dir = str(Path(__file__).resolve().parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "super-secret-production-jwt-key-for-shopping-app-2026"
os.environ["SERVICE_NAME"] = "test-service"
os.environ["SIMULATE_FAILURE_RATE"] = "0.0"
os.environ["PAYMENT_DEFAULT_DELAY_MS"] = "0"

def load_service(service_dir_name: str, pkg_name: str):
    """Dynamically loads a microservice package without sys.modules collisions."""
    base = (Path(root_dir) / "apps" / "services" / service_dir_name / "src").resolve()
    
    # Register package namespace
    pkg_spec = importlib.util.spec_from_file_location(pkg_name, base / "__init__.py")
    if pkg_spec and (base / "__init__.py").exists():
        pkg_mod = importlib.util.module_from_spec(pkg_spec)
        sys.modules[pkg_name] = pkg_mod
        pkg_spec.loader.exec_module(pkg_mod)
    else:
        import types
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [str(base)]
        sys.modules[pkg_name] = pkg_mod

    # Load main
    main_spec = importlib.util.spec_from_file_location(f"{pkg_name}.main", base / "main.py")
    main_mod = importlib.util.module_from_spec(main_spec)
    main_mod.__package__ = pkg_name
    sys.modules[f"{pkg_name}.main"] = main_mod
    main_spec.loader.exec_module(main_mod)
    
    return main_mod
