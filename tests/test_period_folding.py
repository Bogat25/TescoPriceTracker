import pytest
from datetime import datetime, timedelta
from database_manager import _apply_period

@pytest.fixture
def today():
    return datetime.now().strftime("%Y-%m-%d")

@pytest.fixture
def yesterday():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

@pytest.fixture
def last_week():
    return (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

def test_apply_period_empty_history(today):
    periods = []
    fields = {"price": 100, "unit_price": 10}
    is_new = _apply_period(periods, fields, "normal", today)
    
    assert is_new is True
    assert len(periods) == 1
    assert periods[0] == {"price": 100, "unit_price": 10, "start_date": today, "end_date": today}

def test_apply_period_same_data_extend(today, yesterday):
    periods = [{"price": 100, "unit_price": 10, "start_date": yesterday, "end_date": yesterday}]
    fields = {"price": 100, "unit_price": 10}
    
    is_new = _apply_period(periods, fields, "normal", today)
    
    assert is_new is False
    assert len(periods) == 1
    assert periods[0]["start_date"] == yesterday
    assert periods[0]["end_date"] == today

def test_apply_period_data_changed_same_day(today):
    periods = [{"price": 100, "unit_price": 10, "start_date": today, "end_date": today}]
    fields = {"price": 90, "unit_price": 9}
    
    is_new = _apply_period(periods, fields, "normal", today)
    
    assert is_new is True
    assert len(periods) == 1
    assert periods[0]["price"] == 90
    assert periods[0]["start_date"] == today
    assert periods[0]["end_date"] == today

def test_apply_period_gap_new_entry(today, last_week):
    periods = [{"price": 100, "unit_price": 10, "start_date": last_week, "end_date": last_week}]
    fields = {"price": 100, "unit_price": 10}
    
    is_new = _apply_period(periods, fields, "normal", today)
    
    assert is_new is True
    assert len(periods) == 2
    assert periods[-1] == {"price": 100, "unit_price": 10, "start_date": today, "end_date": today}

