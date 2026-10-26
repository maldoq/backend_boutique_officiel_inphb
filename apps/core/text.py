import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_search(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : « Clé USB 32 Go » -> « cle usb 32 go »."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALNUM.sub(" ", without_accents.lower()).strip()


def search_terms(query: str, *, limit: int = 8) -> list[str]:
    """Mots d'une requête utilisateur, normalisés et dédoublonnés (8 au plus)."""
    return list(dict.fromkeys(normalize_search(query).split()))[:limit]
