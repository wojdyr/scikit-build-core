from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scikit_build_core._compat import tomllib
from scikit_build_core.settings.skbuild_schema import (
    generate_skbuild_schema,
    get_skbuild_schema,
)

DIR = Path(__file__).parent.resolve()


def test_compare_schemas():
    """
    Should be the same. If not, run nox -s generate_schema
    """

    assert generate_skbuild_schema() == get_skbuild_schema()


@pytest.mark.parametrize(
    "filepath",
    [
        *DIR.parent.joinpath("docs/examples").glob("**/pyproject.toml"),
        *DIR.joinpath("packages").glob("**/pyproject.toml"),
    ],
)
def test_valid_schemas_files(filepath: Path) -> None:
    api = pytest.importorskip("validate_pyproject.api")

    with filepath.open("rb") as f:
        example = tomllib.load(f)

    validator = api.Validator()
    assert validator(example) is not None


@pytest.mark.parametrize(
    "addition",
    [
        {"minimum-version": 0.3},
        {"random": "not valid"},
        {"logging": {"level": "POODLE"}},
        {"generate": [{"path": "CMakeLists.txt"}]},
        {"generate": [{"path": "me.py", "template": "hi", "template-path": "hello"}]},
        {"generate": [{"path": "me.py", "template": ""}]},
    ],
)
def test_invalid_schemas(addition: dict[str, Any]) -> None:
    fastjsonschema = pytest.importorskip("fastjsonschema")
    api = pytest.importorskip("validate_pyproject.api")

    example_toml = """\
    [project]
    name = "myproj"
    version = "0"

    [tool.scikit-build]
    minimum-version = "0.3"
    """

    example = tomllib.loads(example_toml)
    example["tool"]["scikit-build"].update(**addition)

    validator = api.Validator()
    with pytest.raises(fastjsonschema.JsonSchemaValueException):
        validator(example)


@pytest.mark.parametrize(
    "addition",
    [
        {"generate": [{"path": "CMakeLists.txt", "template": "hi"}]},
        {"generate": [{"path": "me.py", "template-path": "hello"}]},
    ],
)
def test_valid_schemas(addition: dict[str, Any]) -> None:
    api = pytest.importorskip("validate_pyproject.api")

    example_toml = """\
    [project]
    name = "myproj"
    version = "0"

    [tool.scikit-build]
    minimum-version = "0.3"
    """

    example = tomllib.loads(example_toml)
    example["tool"]["scikit-build"].update(**addition)

    validator = api.Validator()
    validator(example)
