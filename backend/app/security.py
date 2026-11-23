"""Password hashing/policy and signed access tokens (HS256, standard library only)."""
import base64, hashlib, hmac, json, secrets, time
from .config import settings

TOKEN_ISSUER = "exam-monitor"
MIN_SECRET_LENGTH = 32
_WEAK_SECRET_MARKERS = ("replace_with", "change-this", "changeme", "development-only", "your-secret",
                        "example", "secret-key-here")
_COMMON_PASSWORDS = {"changeme123!", "password123!", "password1234", "administrator1", "123456789012",
                     "qwertyuiop12", "welcome12345", "admin123456!", "letmein12345"}


class SecretKeyError(RuntimeError):
    pass


def check_secret_key(key: str) -> list[str]:
    """Return a list of problems with the signing key (empty list = acceptable)."""
    problems = []
    if not key:
        problems.append("SECRET_KEY is not set")
        return problems
    if len(key) < MIN_SECRET_LENGTH:
        problems.append(f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters")
    lowered = key.lower()
    if any(m in lowered for m in _WEAK_SECRET_MARKERS):
        problems.append("SECRET_KEY looks like a placeholder value")
    if len(set(key)) < 10:
        problems.append("SECRET_KEY has too little variety; generate one with: python -m app.cli gen-secret")
    return problems


def get_secret_key() -> bytes:
    problems = check_secret_key(settings.secret_key)
    if problems:
        raise SecretKeyError("; ".join(problems) + ". Generate one with: python -m app.cli gen-secret")
    return settings.secret_key.encode()


# ---------------------------------------------------------------- passwords
def validate_password_strength(password: str, username: str | None = None) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("Password must be at least 12 characters long")
    if len(password) > 128:
        problems.append("Password must be at most 128 characters long")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("Password must contain at least one letter and one digit")
    if len(set(password)) < 5:
        problems.append("Password has too little variety")
    if password.lower() in _COMMON_PASSWORDS:
        problems.append("Password is too common")
    if username and len(username) >= 3 and username.lower() in password.lower():
        problems.append("Password must not contain the username")
    return problems


def hash_password(password: str) -> str:
    rounds = settings.pbkdf2_rounds
    if settings.environment != "test" and rounds < 200_000:
        raise RuntimeError("PBKDF2_ROUNDS below 200000 is only allowed when ENVIRONMENT=test")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Spend roughly the same time as a real check (unknown / inactive accounts)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _dummy_hash)


# ------------------------------------------------------------------- tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(signing_input: bytes) -> str:
    return _b64(hmac.new(get_secret_key(), signing_input, hashlib.sha256).digest())


def create_access_token(subject: str, role: str, token_version: int = 0, session_id: str | None = None) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"sub": subject, "role": role, "ver": token_version, "iss": TOKEN_ISSUER,
              "iat": now, "exp": now + settings.access_token_minutes * 60, "jti": secrets.token_hex(8)}
    if session_id:
        claims["sid"] = session_id
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{header}.{payload}.{_sign(f'{header}.{payload}'.encode())}"


def decode_token(token: str):
    """Return the claims dict, or None for any invalid/expired/tampered token."""
    try:
        header_b64, payload_b64, signature = token.split(".")
        header = json.loads(_unb64(header_b64))
        if header.get("alg") != "HS256":
            return None
        if not hmac.compare_digest(signature, _sign(f"{header_b64}.{payload_b64}".encode())):
            return None
        data = json.loads(_unb64(payload_b64))
        if data.get("iss") != TOKEN_ISSUER:
            return None
        if int(data.get("exp", 0)) <= int(time.time()):
            return None
        if not data.get("sub") or not data.get("role"):
            return None
        return data
    except SecretKeyError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return None


# The 0.1.0 starter seeded this account; legacy databases may still contain it.
LEGACY_DEFAULT_PASSWORD = "ChangeMe123!"


# ------------------------------------------------- one-time tokens (reset / activation)
def new_one_time_token() -> tuple[str, str]:
    """(token to e-mail, sha256 hash to store). The plain token is never stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_one_time_token(raw)


def hash_one_time_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_temporary_password() -> str:
    """Policy-compliant random password for administrator-initiated resets (shown once)."""
    return "Tmp-" + secrets.token_urlsafe(9) + "-" + str(secrets.randbelow(90) + 10)
