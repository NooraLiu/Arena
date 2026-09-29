import pytest

from play import session as S


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Point every file the session driver touches at tmp_path (like ARENA_SANDBOX)."""
    play_live = str(tmp_path / "play_live")
    app_live = str(tmp_path / "app_live")
    monkeypatch.setattr(S, "STATE", str(tmp_path / "game.pkl"))
    monkeypatch.setattr(S, "APP_LIVE", app_live)
    monkeypatch.setattr(S, "PLAY_LIVE", play_live)
    monkeypatch.setattr(S, "LIVE", play_live)
    monkeypatch.setattr(S, "PROMPT_DIR", f"{play_live}/prompts")
    monkeypatch.setattr(S, "DECISION_DIR", f"{play_live}/decisions")
    monkeypatch.setattr(S, "HUMAN_DIR", f"{play_live}/human")
    return S
