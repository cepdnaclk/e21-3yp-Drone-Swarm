from pathlib import Path
import json
import py_compile


REPO_ROOT = Path(__file__).resolve().parents[1]


def iter_python_files():
    for path in REPO_ROOT.rglob("*.py"):
        if any(part.startswith(".") for part in path.parts):
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def test_python_files_have_valid_syntax():
    failures = []

    for path in iter_python_files():
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.relative_to(REPO_ROOT)}: {exc.msg}")

    assert not failures, "Syntax errors found:\n" + "\n".join(failures)


def test_docs_index_json_is_valid():
    index_path = REPO_ROOT / "docs" / "data" / "index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert isinstance(data.get("team"), list) and data["team"]
    assert isinstance(data.get("supervisors"), list) and data["supervisors"]
    assert isinstance(data.get("tags"), list)


def test_docs_index_json_people_have_required_fields():
    index_path = REPO_ROOT / "docs" / "data" / "index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))

    for person in data["team"]:
        assert person.get("name")
        assert person.get("email")
        assert person.get("eNumber")

    for supervisor in data["supervisors"]:
        assert supervisor.get("name")
        assert supervisor.get("email")
