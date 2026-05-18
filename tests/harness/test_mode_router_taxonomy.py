from harness.services.mode_router import ModeRouter

R = ModeRouter()

MATCHING = [
    "derive a new column in data/sales.csv",
    "one hot encode the category field",
    "min max normalize the revenue column",
    "add a rolling average column",
    "join data/a.csv with data/b.csv",
]
NON_MATCHING = [
    "hello there",
    "what is the weather",
    "tell me a joke",
]


def test_transformation_inputs_route_to_analyst():
    for text in MATCHING:
        assert R.route(text).mode == "analyst", text


def test_non_transformation_inputs_do_not_route_to_analyst():
    for text in NON_MATCHING:
        assert R.route(text).mode != "analyst", text
