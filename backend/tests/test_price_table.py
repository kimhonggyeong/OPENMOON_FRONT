from pathlib import Path

from types import SimpleNamespace

from backend.app.services.external_price_engine import apply_prices


def test_banner_exact_price(tmp_path: Path):
    del tmp_path
    data_dir = Path(__file__).resolve().parents[1] / "data" / "source"
    item = SimpleNamespace(
        product_name="현수막",
        specification="4000mm x 600mm",
        quantity=1,
        unit="개",
        unit_price=None,
        amount=None,
    )
    decisions = apply_prices(
        items=[item],
        customer_organization="테스트기관",
        quotation_database_path=data_dir / "quotation_history.db",
        price_database_path=data_dir / "price_table.db",
    )
    assert len(decisions) == 1
    assert decisions[0].unit_price is not None
    assert decisions[0].amount is not None
    assert decisions[0].source in {"history", "price_table"}
