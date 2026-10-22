import re
import unicodedata


def match_key(value: str | None) -> str:
    """Text as rules and counterparty aliases compare it: lowercase, no accents, single spaces.
    Digits stay (unlike the fingerprint normalizer), so "4450" or "IVA 23" can be matched."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w]+", " ", without_accents).split())
