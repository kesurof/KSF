import re


INSTANCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


def validate_instance(value: str) -> str:
    value = value.strip()
    if not INSTANCE_RE.fullmatch(value):
        raise ValueError(
            "Le nom d'instance doit contenir 1 a 63 caracteres: lettres minuscules, chiffres, - ou _."
        )
    return value


def validate_port(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError("Le port doit etre compris entre 1 et 65535.")
    return value


def validate_host(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not HOST_RE.fullmatch(value):
        raise ValueError("Le host doit etre un nom de domaine complet valide.")
    return value


def validate_subdomain(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise ValueError("Le sous-domaine est invalide.")
    return value


def validate_allowed_domain(value: str, domains: list[str]) -> str:
    domain = validate_host(value)
    if domain not in {item.lower() for item in domains}:
        raise ValueError("Le domaine n'est pas autorise pour cette application.")
    return domain


def validate_allowed_host(value: str, domains: list[str]) -> tuple[str, str, str]:
    host = validate_host(value)
    for domain in sorted((item.lower() for item in domains), key=len, reverse=True):
        suffix = f".{domain}"
        if host.endswith(suffix):
            subdomain = host[:-len(suffix)]
            if subdomain and "." not in subdomain:
                return host, domain, validate_subdomain(subdomain)
    raise ValueError("Le host doit etre un sous-domaine d'un domaine autorise, jamais le domaine racine.")
