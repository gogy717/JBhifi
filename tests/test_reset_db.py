"""scripts/reset_db.py drops a database, so it refuses any name it must never drop."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "reset_db.py"
spec = importlib.util.spec_from_file_location("reset_db", SCRIPT)
reset_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset_db)


def test_the_dev_database_may_be_rebuilt():
    assert reset_db.refusal("jbhifi_sp4", "jbhifi_test_sp4") is None


def test_an_empty_name_is_refused():
    assert reset_db.refusal("", "jbhifi_test") is not None
    assert reset_db.refusal(None, "jbhifi_test") is not None


def test_postgresql_system_databases_are_refused():
    for name in ("postgres", "template0", "template1"):
        assert name in reset_db.refusal(name, "jbhifi_test")


def test_the_test_database_is_refused():
    assert "POSTGRES_TEST_DB" in reset_db.refusal("jbhifi_test", "jbhifi_test")
