"""scripts/demo.py warns when the API would refuse sign-ins from the web port it starts the web app on."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo.py"
spec = importlib.util.spec_from_file_location("demo", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_a_listed_web_origin_needs_no_warning():
    assert demo.missing_web_origin("http://localhost:3000,http://127.0.0.1:3000", 3000) is None


def test_an_unlisted_web_port_is_named():
    assert demo.missing_web_origin("http://localhost:3000,http://127.0.0.1:3000", 3004) == "http://localhost:3004"
    assert demo.missing_web_origin(None, 3000) == "http://localhost:3000"
