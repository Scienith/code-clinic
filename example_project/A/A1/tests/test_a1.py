from example_project.A.A1 import process_data


def test_process_data_smoke():
    # Should run even if dependent functions are simple
    report = process_data([{"value": 1}, {"value": 2}])
    assert "Data Analysis Report" in report


def test_intentional_failure_for_demo():
    # This failing test demonstrates that when deps contain stubs, gate is relaxed
    assert 1 == 2

