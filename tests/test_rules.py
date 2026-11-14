from hab.rules import Rule, RuleEngine


def make_engine(tmp_path):
    sent = []
    engine = RuleEngine(tmp_path / "rules.json", lambda dev, cmd: sent.append((dev, cmd)))
    return engine, sent


def fan_rule(**kw):
    base = dict(name="cool down", when_device="living_room/climate", when_field="temperature_c",
                op=">", value=28, then_device="living_room/fan", then_command={"on": True}, cooldown_s=60)
    return Rule(**{**base, **kw})


def test_fires_on_rising_edge_only(tmp_path):
    engine, sent = make_engine(tmp_path)
    engine.add(fan_rule())
    engine.on_state("living_room/climate", {"temperature_c": 27}, now=0)
    engine.on_state("living_room/climate", {"temperature_c": 29}, now=100)
    engine.on_state("living_room/climate", {"temperature_c": 30}, now=200)  # still hot: no repeat
    assert sent == [("living_room/fan", {"on": True})]


def test_cooldown_blocks_flapping(tmp_path):
    engine, sent = make_engine(tmp_path)
    engine.add(fan_rule())
    for i, temp in enumerate([29, 27, 29]):  # crosses twice within 60s
        engine.on_state("living_room/climate", {"temperature_c": temp}, now=1000 + i * 10)
    assert len(sent) == 1


def test_ignores_other_devices_and_missing_fields(tmp_path):
    engine, sent = make_engine(tmp_path)
    engine.add(fan_rule())
    engine.on_state("hallway/motion", {"temperature_c": 40}, now=0)
    engine.on_state("living_room/climate", {"humidity_pct": 90}, now=0)
    engine.on_state("living_room/climate", {"temperature_c": "n/a"}, now=0)  # bad reading
    assert sent == []


def test_rules_persist(tmp_path):
    engine, _ = make_engine(tmp_path)
    rule = engine.add(fan_rule())
    reloaded, _ = make_engine(tmp_path)
    assert rule.id in reloaded.rules
    assert reloaded.delete(rule.id)
    assert make_engine(tmp_path)[0].rules == {}


def test_rejects_bad_operator(tmp_path):
    engine, _ = make_engine(tmp_path)
    try:
        engine.add(fan_rule(op="=>"))
    except ValueError:
        return
    raise AssertionError("expected ValueError")
