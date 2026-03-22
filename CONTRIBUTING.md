# Contributing to LovensePy

Thank you for your interest in contributing to LovensePy! This document provides guidelines for contributing to the project.

## Getting Started

### Prerequisites

- Python **3.12 or higher** (matches `requires-python` in `pyproject.toml`)
- [pip](https://pip.pypa.io/) for package management

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/lovensepy.git
   cd lovensepy
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install in development mode with dev dependencies**

   ```bash
   pip install -e ".[dev]"
   ```

4. **Run tests to verify setup**

   ```bash
   pytest tests/test_unit.py tests/test_async_clients.py -v
   ```

   For the same fast checks as CI (see `.github/workflows/tests.yml`), run all
   listed unit test modules, or use `python -m tests.run_all` for the full
   ordered suite (including integration phases that need devices or tokens).

## How to Contribute

### Reporting Bugs

- Use the [Bug Report](https://github.com/koval01/lovensepy/issues/new?template=bug_report.md) template
- Include steps to reproduce, expected vs actual behavior, and environment details
- For integration tests, mention which Lovense API (LAN, Server, Socket, Toy Events) you're using

### Suggesting Features

- Use the [Feature Request](https://github.com/koval01/lovensepy/issues/new?template=feature_request.md) template
- Describe the use case and how it fits with the existing API design

### Pull Requests

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

2. **Make your changes**
   - Follow existing code style (PEP 8)
   - Add or update tests as needed
   - Update documentation if the API changes

3. **Run tests**
   ```bash
   pytest tests/ -v
   ```

4. **Commit** with clear messages:
   ```bash
   git add .
   git commit -m "Add support for X"  # or "Fix Y when Z"
   ```

5. **Push and open a Pull Request**
   - Use the PR template
   - Link related issues if applicable
   - Ensure CI passes

## Code Style

- Use **PEP 8** style guidelines
- Use type hints where appropriate
- Keep functions focused and reasonably sized
- Add docstrings for public APIs

## Project Structure

- `lovensepy/` — main package
- `examples/` — usage examples
- `tests/` — unit and integration tests
- `docs/` — Markdown documentation (MkDocs source; published to [GitHub Pages](https://lovensepy.koval-dev.org/))
- `mkdocs.yml` — MkDocs site configuration
- Integration tests require env vars (see [docs/appendix.md — Tests](docs/appendix.md#tests))

### Documentation site

Preview the docs site locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

Or with uv: `uv sync --extra docs` then `uv run mkdocs serve`. CI builds with `mkdocs build --strict` on pushes that touch `docs/` or `mkdocs.yml`.

## Questions?

Open an issue with the `question` label or start a discussion.

Thank you for contributing!
