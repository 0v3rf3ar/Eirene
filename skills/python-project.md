---
name: python-project
description: Lay out, test and package a Python project the way this machine expects.
---

Use this when creating a Python project from scratch, or when adding tests,
dependencies or packaging to an existing one.

## Layout

```
project/
  pyproject.toml
  src/<package>/__init__.py
  tests/test_<area>.py
  .gitignore
```

Prefer `src/` layout: it stops the tests importing the working copy by accident.

## pyproject.toml

```toml
[project]
name = "<package>"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

## The environment

Many distributions mark the system Python as externally managed, so `pip install`
fails outside a virtual environment. Always work in one:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Call `.venv/bin/python` by path. Do not rely on `activate`, because each command
runs in its own shell.

## Tests

One test per behaviour, named for what it proves: `test_a_missing_file_is_reported`,
not `test_read_2`. Assert on the outcome the user would notice, not on internals.

```sh
.venv/bin/python -m pytest -q
```

Run the suite before saying the work is done, and quote the real result.

## Things to avoid

- Bare `except:` — catch the exception you expect.
- Mutable default arguments (`def f(items=[])`).
- Printing for diagnostics in a library; raise or return instead.
- Adding a dependency for something the standard library already does.
