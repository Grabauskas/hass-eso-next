import importlib
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ESO_DIR = REPO_ROOT / "custom_components" / "eso"

# Register a synthetic top-level package "eso" pointing at the component
# directory. This lets us import eso.form_parser / eso.eso_client /
# eso.imap_client (which use relative imports) WITHOUT executing
# custom_components/eso/__init__.py, whose Home Assistant imports are
# unavailable in unit tests.
if "eso" not in sys.modules:
    pkg = types.ModuleType("eso")
    pkg.__path__ = [str(ESO_DIR)]
    sys.modules["eso"] = pkg


@pytest.fixture
def eso_module():
    def _load(name):
        return importlib.import_module(f"eso.{name}")
    return _load


@pytest.fixture
def docs_path():
    return REPO_ROOT / "docs"


@pytest.fixture
def fixtures_path():
    return Path(__file__).resolve().parent / "fixtures"
