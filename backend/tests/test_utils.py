from backend.app.services.utils import normalize_customer_name, parse_dimensions


def test_parse_mixed_dimensions():
    assert parse_dimensions("4000mm * 600mm")[:2] == (4000.0, 600.0)
    assert parse_dimensions("350*60cm")[:2] == (3500.0, 600.0)
    assert parse_dimensions("4m x 60cm")[:2] == (4000.0, 600.0)


def test_normalize_company_prefix():
    assert normalize_customer_name("(주) 디지털 귀하") == "디지털"
    assert normalize_customer_name("주식회사 디지털") == "디지털"
