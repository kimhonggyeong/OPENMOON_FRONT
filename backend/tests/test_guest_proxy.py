from backend.app import guest_proxy


def test_upstream_target_preserves_company_scope_query():
    guest_proxy.set_guest_upstream("http://192.168.0.10:54837")

    target = guest_proxy._upstream_target(
        "/api/mails/31/history",
        "scope=company",
    )

    assert target == (
        "http://192.168.0.10:54837/"
        "api/mails/31/history?scope=company"
    )


def test_upstream_target_preserves_encoded_search_and_filter():
    guest_proxy.set_guest_upstream("http://192.168.0.10:54837/")

    target = guest_proxy._upstream_target(
        "api/mails",
        "status=REVIEW_REQUIRED&search=%EC%B6%A9%EB%82%A8",
    )

    assert target.endswith(
        "/api/mails?status=REVIEW_REQUIRED&search=%EC%B6%A9%EB%82%A8"
    )
