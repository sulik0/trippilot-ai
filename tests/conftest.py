import os


def pytest_ignore_collect(collection_path, config):
    """Keep live-LLM demo scripts out of the default offline test run."""
    if os.getenv("TRIPPILOT_RUN_INTEGRATION_TESTS") == "1":
        return False
    return collection_path.name != "test_smoke.py"
