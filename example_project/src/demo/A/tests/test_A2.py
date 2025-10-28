from demo.A.A2 import validate_input


def test_validate_input_true():
    assert validate_input({"id": 1, "value": 2}) is True


def test_validate_input_false():
    assert validate_input("oops") is False
