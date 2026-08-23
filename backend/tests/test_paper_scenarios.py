from services.paper_scenarios import scenario_for_index


def test_paper_scenarios_cover_all_three_jianghe_setups():
    names = []
    sides = []
    for index in range(3):
        scenario = scenario_for_index(index, "BTC/USDT")
        names.append(scenario.name)
        sides.append(scenario.evaluation.side)
        assert scenario.evaluation.candidate is True
        assert scenario.evaluation.invalidation_reference is not None
        assert scenario.evaluation.entry_reference is not None

    assert names == [
        "TREND_PULLBACK_CONTINUATION",
        "BREAKOUT_CONTINUATION",
        "SECOND_PUSH_FAILURE",
    ]
    assert sides == ["LONG", "LONG", "SHORT"]


def test_paper_scenario_rotation_is_deterministic():
    assert scenario_for_index(3, "ETH/USDT").name == "TREND_PULLBACK_CONTINUATION"
    assert scenario_for_index(4, "ETH/USDT").name == "BREAKOUT_CONTINUATION"
    assert scenario_for_index(5, "ETH/USDT").name == "SECOND_PUSH_FAILURE"
