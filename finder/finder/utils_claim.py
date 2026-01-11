# finder/utils_claim.py
import hashlib, random
from urllib.parse import urlparse

def domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
        host = host.replace("www.", "")
        return host
    except Exception:
        return ""

def gen_code() -> str:
    return f"{random.randint(100000, 999999)}"

def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()
