from demo.C import always_true


def test_c_should_pass_but_we_fail():
    # Intentionally failing to demonstrate component gate behavior
    assert always_true() is False
