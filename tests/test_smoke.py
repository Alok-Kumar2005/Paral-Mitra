"""Smoke test verifying project structure and imports."""

def test_project_structure_import():
    import src.engine
    import src.connectors
    import src.agent
    import src.bot
    import src.handlers
    import src.common

    assert src.engine is not None
    assert src.connectors is not None
    assert src.agent is not None
    assert src.bot is not None
    assert src.handlers is not None
    assert src.common is not None
