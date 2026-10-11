# Development

Use Python 3.11–3.13 and install the package in a virtual environment:

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
ruff format --check src tests scripts
pytest
```

Tests run without real API keys, embeddings, or an ns-3 installation. Use fake clients and temporary directories when adding tests for model or simulator behavior. Live experiments should be run separately with a matching ns-3 installation.

The supported implementation lives in `src/agens3/`. Put scenario prompts in `examples/prompts/`, user documentation in `docs/`, and meaningful regression tests in `tests/`. Keep credentials, vector databases, simulator builds, and run logs out of commits. `archive/` contains historical references and is excluded from linting and packaging.

When changing an agent role or graph edge, update `docs/architecture.md`. Report the concrete behavior change and the relevant validation in pull requests.
