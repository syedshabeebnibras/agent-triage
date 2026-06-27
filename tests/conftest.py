"""Pytest config: stop collecting the schema TestResult model as a test class."""

collect_ignore_glob: list[str] = []


def pytest_collection_modifyitems(config, items):
    pass
