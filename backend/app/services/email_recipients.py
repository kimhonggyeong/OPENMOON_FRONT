import re


def normalize_recipients(values: list[str]) -> list[str]:
    if not values or len(values) > 50:
        raise ValueError("발송 주소를 1개 이상, 50개 이하로 입력해주세요.")
    result = []
    seen = set()
    for value in values:
        address = value.strip()
        if len(address) > 254 or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+",
            address,
        ) or address.split("@")[0].startswith(".") or address.split("@")[0].endswith(".") or ".." in address:
            raise ValueError("각 입력칸에 올바른 이메일 주소를 하나씩 입력해주세요.")
        if address.casefold() not in seen:
            result.append(address)
            seen.add(address.casefold())
    return result
