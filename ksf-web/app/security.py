import re


def validate_app_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([a-z0-9\-]*[a-z0-9])?", name))


def validate_container_name(name: str, valid_names: list[str]) -> bool:
    return name in valid_names
