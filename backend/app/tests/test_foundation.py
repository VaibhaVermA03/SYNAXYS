import ast, json, logging, pathlib
from app.core.exceptions import NotFound, AppError
from app.core.logging import RedactingJsonFormatter

MODELS = pathlib.Path(__file__).resolve().parents[1] / "models" / "entities.py"


def test_error_envelope_has_no_internals():
    env = NotFound("Repository not found").to_envelope()
    assert env == {"error": {"code": "not_found", "message": "Repository not found"}}
    assert AppError().status_code == 500


def test_logging_redacts_secrets():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "token ghp_%s leaked", ("a" * 36,), None)
    out = json.loads(RedactingJsonFormatter().format(rec))
    assert "ghp_" not in out["msg"] and "[REDACTED]" in out["msg"]


def _tables_and_fks():
    tree = ast.parse(MODELS.read_text())
    tables, fks = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__tablename__" for t in node.targets):
            tables.add(node.value.value)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ForeignKey":
            fks.append(node.args[0].value)
    return tables, fks


def test_model_foreign_keys_reference_existing_tables_and_ondelete_set():
    tables, fks = _tables_and_fks()
    assert len(tables) == 18
    for fk in fks:
        assert fk.split(".")[0] in tables, fk


def test_no_plaintext_token_columns():
    src = MODELS.read_text()
    assert "access_token:" not in src and "access_token_enc" in src
