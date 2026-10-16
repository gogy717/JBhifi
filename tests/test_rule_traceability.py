"""The rule traceability table (docs/rule-traceability.md), checked against the database and the tests so it can't
go stale: every brNN_… name in the catalog is in the table, every name an error can carry is asserted by a test,
every rule has an assertion in test_business_rules.py (the project's convention), every rule has its own row, and
the table names nothing the database doesn't have.

"Asserted" means the name is a string literal inside an `assert` statement or a `violates(...)` call, found by
parsing the test files (so a name in a comment or docstring doesn't count).
"""
import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "docs" / "rule-traceability.md"
RULE_NAME = re.compile(r"br(\d{2})_[a-z0-9_]+")
# Names no test can assert, each with its reason. Empty: every name an error can carry is asserted today.
EXEMPT: dict[str, str] = {}


@pytest.fixture
def catalog(cur) -> dict[str, set[str]]:
    """The brNN_… names in the database. `~ '^br[0-9]{2}_'`, not LIKE 'br%', which would also take brand_*."""
    cur.execute("""SELECT conname FROM pg_constraint
                   WHERE conname ~ '^br[0-9]{2}_' AND connamespace = 'public'::regnamespace""")
    declared = {row["conname"] for row in cur.fetchall()}        # CHECK, UNIQUE, FK, domain, constraint trigger
    cur.execute("""SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
                   WHERE i.relname ~ '^br[0-9]{2}_'
                     AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.oid)""")
    indexes = {row["relname"] for row in cur.fetchall()}         # a partial unique index has no constraint
    cur.execute("""SELECT tg.tgname, p.proname, p.prosrc, encode(tg.tgargs, 'escape') AS args
                   FROM pg_trigger tg
                   JOIN pg_proc p ON p.oid = tg.tgfoid
                   WHERE NOT tg.tgisinternal AND p.pronamespace = 'public'::regnamespace""")
    rows = cur.fetchall()
    raised = set()
    for row in rows:
        # The names a trigger reports: its function's CONSTRAINT = '…' literals, and its arguments (the shared
        # append-only function raises TG_ARGV[0], so a _truncate trigger shares its row trigger's name).
        raised |= set(re.findall(r"CONSTRAINT\s*=\s*'([a-z0-9_]+)'", row["prosrc"]))
        raised |= {arg for arg in row["args"].split("\\000") if arg}
    return {
        "declared": declared,
        "indexes": indexes,
        "triggers": {row["tgname"] for row in rows if RULE_NAME.fullmatch(row["tgname"])},
        "raised": {name for name in raised if RULE_NAME.fullmatch(name)},
        "functions": {row["proname"] for row in rows},
    }


def reportable(catalog) -> set[str]:
    """The names an error's constraint_name — the API's error code — can be."""
    return catalog["declared"] | catalog["indexes"] | catalog["raised"]


def every_name(catalog) -> set[str]:
    return reportable(catalog) | catalog["triggers"]


def asserted() -> dict[str, set[str]]:
    """name -> the test files that assert it."""
    found = defaultdict(set)
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and RULE_NAME.fullmatch(node.value)):
                continue
            outer = parents.get(node)
            while outer is not None:
                called = getattr(outer, "func", None)
                if isinstance(outer, ast.Assert) or getattr(called, "id", None) == "violates":
                    found[node.value].add(path.name)
                    break
                outer = parents.get(outer)
    return found


def table_text() -> str:
    return TABLE.read_text()


def test_every_rule_name_in_the_database_is_in_the_traceability_table(catalog):
    named = set(re.findall(r"`([a-z0-9_]+)`", table_text()))
    assert sorted(every_name(catalog) - named) == []


def test_every_name_an_error_can_carry_is_asserted_by_a_test(catalog):
    assert all(reason.strip() for reason in EXEMPT.values()), "every exemption says why"
    assert sorted(set(EXEMPT) - reportable(catalog)) == [], "exempt only names the database has"
    assert sorted(reportable(catalog) - set(asserted()) - set(EXEMPT)) == []


def test_every_rule_has_an_assertion_in_test_business_rules(catalog):
    # Project convention: every BR gets a test in tests/test_business_rules.py that violates it and asserts
    # the brNN_… name.
    rules = {RULE_NAME.fullmatch(name).group(1) for name in every_name(catalog)}
    covered = {RULE_NAME.fullmatch(name).group(1)
               for name, files in asserted().items() if "test_business_rules.py" in files}
    assert sorted(rules - covered) == []


def test_every_rule_has_its_own_row(catalog):
    rules = {RULE_NAME.fullmatch(name).group(1) for name in every_name(catalog)}
    rows = set(re.findall(r"^\| BR(\d{2}) \|", table_text(), flags=re.M))
    assert (sorted(rules - rows), sorted(rows - rules)) == ([], [])


def test_the_table_names_nothing_the_database_does_not_have(catalog):
    mentioned = {match.group(0) for match in re.finditer(r"\bbr\d{2}_[a-z0-9_]+", table_text())}
    assert sorted(mentioned - every_name(catalog) - catalog["functions"]) == []


def test_every_test_the_table_cites_exists():
    defined = {node.name for path in (ROOT / "tests").glob("test_*.py")
               for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.FunctionDef)}
    files = {path.name for path in (ROOT / "tests").glob("test_*.py")}
    cited = set(re.findall(r"\b(test_[a-z0-9_]+)\b(?!\.py)", table_text()))
    assert (sorted(cited - defined - {name.removesuffix(".py") for name in files}),
            sorted(set(re.findall(r"\b(test_[a-z0-9_]+\.py)\b", table_text())) - files)) == ([], [])
