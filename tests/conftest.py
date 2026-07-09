import os


OFFLINE_TESTS = {
    "test_agent_contracts.py",
    "test_smoke.py",
}


def pytest_ignore_collect(collection_path, config):
    """Keep live-LLM demo scripts out of the default offline test run."""
    if os.getenv("TRIPPILOT_RUN_INTEGRATION_TESTS") == "1":
        return False
    return collection_path.name not in OFFLINE_TESTS
