from riverr.core import keys as keymod


def test_defaults_present():
    km = keymod.load()
    assert "j" in km["move_down"]
    assert "k" in km["move_up"]
    assert "q" in km["quit"]
    assert "ctrl+r" in km["refresh"]
    assert "R" in km["mark_all_read"]
    # space pages down, ctrl+space pages up (universal)
    assert "space" in km["page_down"]
    assert "ctrl+space" in km["page_up"]


def test_user_override_merges(tmp_path):
    p = tmp_path / "keys.toml"
    p.write_text(
        '[keys]\n'
        'move_down = ["n"]\n'
        'quit = "Q"\n'
    )
    km = keymod.load(p)
    assert km["move_down"] == ["n"]
    assert km["quit"] == ["Q"]
    # untouched keeps default
    assert "ctrl+r" in km["refresh"]


def test_textual_bindings_skips_chords():
    pairs = keymod.textual_bindings()
    for key, _, _ in pairs:
        assert "," not in key


def test_bindings_for_filters_actions():
    pairs = keymod.bindings_for(["quit", "refresh"])
    actions = {a for _, a, _ in pairs}
    assert actions == {"quit", "refresh"}


def test_get_behavior_defaults_and_override(tmp_path):
    # defaults when no file
    b = keymod.get_behavior(None)
    assert b["expanded_j"] == "open_next"
    assert b["expanded_k"] == "close_and_prev"
    # honoured override
    p = tmp_path / "keys.toml"
    p.write_text(
        '[keys]\nquit = "q"\n'
        '[behavior]\n'
        'expanded_j = "collapse_only"\n'
        'expanded_k = "collapse_only"\n'
    )
    b = keymod.get_behavior(p)
    assert b["expanded_j"] == "collapse_only"
    assert b["expanded_k"] == "collapse_only"
    # invalid value falls back to default
    p.write_text('[behavior]\nexpanded_j = "weird"\n')
    b = keymod.get_behavior(p)
    assert b["expanded_j"] == "open_next"


def test_app_picks_up_keymap_override(tmp_path, monkeypatch):
    """Custom keys.toml that remaps quit q -> Q should propagate to v7's bindings."""
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    (cfg / "riverr").mkdir(parents=True)
    (state / "riverr").mkdir(parents=True)
    (cfg / "riverr" / "keys.toml").write_text(
        '[keys]\n'
        'quit = "Q"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))

    from riverr.variants.v7_river_plus.app import V7App
    from riverr.core.storage import Storage
    s = Storage(state / "riverr" / "state.db")
    try:
        app = V7App(storage=s)
        mapping = app._bindings.key_to_bindings
        assert "Q" in mapping
        assert any(b.action == "quit" for b in mapping["Q"])
        if "q" in mapping:
            assert not any(b.action == "quit" for b in mapping["q"])
    finally:
        s.close()
