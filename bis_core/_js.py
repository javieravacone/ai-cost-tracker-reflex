"""JavaScript-compatible primitives used by the port so outputs match the TypeScript app.

The TS app relies on JS semantics that differ from Python's: `Math.round` (half up, not
banker's rounding), `Date.parse` / `toISOString`, `Number(...)` string parsing,
`String.prototype.localeCompare` (ICU collation) and `Intl.NumberFormat` / `toFixed` rounding
on the exact binary value. Everything here is pure stdlib.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any
from urllib.parse import quote

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DAY_MS = 24 * 60 * 60 * 1000

# ---------------------------------------------------------------------------
# Numbers


def is_finite(n: Any) -> bool:
    """`Number.isFinite`: true only for finite numbers (bool is not a number in JS)."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return False
    try:
        return math.isfinite(n)
    except OverflowError:  # huge int
        return False


def is_integer(n: Any) -> bool:
    """`Number.isInteger`."""
    return is_finite(n) and float(n).is_integer()


def js_round(x: float) -> float | int:
    """`Math.round`: rounds half up (towards +∞). Returns an int for finite input."""
    if isinstance(x, int) and not isinstance(x, bool):
        return x
    if not math.isfinite(x):
        return x
    r = math.floor(x + 0.5) if abs(x) < 2**52 else int(x)
    if r == 0 and math.copysign(1.0, x) < 0:
        return -0.0  # Math.round(-0.4) is -0
    return r


_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_JS_WS = " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def js_number(value: Any) -> float | int:
    """`Number(value)` for strings, numbers, None (NaN) and lists (first element semantics are
    not emulated; lists give NaN unless they hold a single convertible value)."""
    if value is None:
        return math.nan
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        if len(value) == 0:
            return 0
        if len(value) == 1:
            return js_number(str(value[0]) if value[0] is not None else "")
        return math.nan
    s = str(value).strip(_JS_WS)
    if s == "":
        return 0
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    m = re.fullmatch(r"0([xXoObB])([0-9a-fA-F]+)", s)
    if m:
        base = {"x": 16, "o": 8, "b": 2}[m.group(1).lower()]
        try:
            return int(m.group(2), base)
        except ValueError:
            return math.nan
    if _NUM_RE.fullmatch(s):
        f = float(s)
        return int(f) if f.is_integer() and abs(f) < 2**53 else f
    return math.nan


def num_str(n: float | int) -> str:
    """`String(n)` for ordinary numbers (integers without ".0")."""
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if math.isnan(n):
        return "NaN"
    if math.isinf(n):
        return "Infinity" if n > 0 else "-Infinity"
    if n.is_integer() and abs(n) < 1e21:
        return str(int(n))
    r = repr(n)
    if "e" in r:
        mant, exp = r.split("e")
        sign = "-" if exp.startswith("-") else "+"
        return f"{mant}e{sign}{exp.lstrip('+-').lstrip('0') or '0'}"
    return r


_CTX = Context(prec=80)


def _round_decimal(x: float, frac: int) -> Decimal:
    """Exact binary value of `x` rounded to `frac` decimals, ties away from zero (ECMA-402 / toFixed)."""
    return Decimal(x).quantize(Decimal(1).scaleb(-frac), rounding=ROUND_HALF_UP, context=_CTX)


def to_fixed(x: float, digits: int) -> str:
    """`Number.prototype.toFixed` for |x| < 1e21."""
    if not math.isfinite(x):
        return num_str(x)
    if abs(x) >= 1e21:
        return num_str(x)
    neg = x < 0
    d = _round_decimal(abs(x), digits)
    s = f"{d:.{digits}f}"
    return f"-{s}" if neg else s


def to_precision_number(x: float, precision: int) -> float:
    """`Number(x.toPrecision(precision))`."""
    if not math.isfinite(x) or x == 0:
        return x
    d = Decimal(x)
    exp = d.adjusted()
    q = d.quantize(Decimal(1).scaleb(exp - precision + 1), rounding=ROUND_HALF_UP, context=_CTX)
    return float(q)


def intl_number(
    x: float,
    min_frac: int = 0,
    max_frac: int = 3,
    grouping: bool = True,
) -> str:
    """`Intl.NumberFormat("en-US", {...}).format(x)` (decimal style, halfExpand rounding).

    Negative values that round to zero keep the sign ("-0"), like ICU's signDisplay "auto".
    """
    if isinstance(x, float) and math.isnan(x):
        return "NaN"
    if isinstance(x, float) and math.isinf(x):
        return "∞" if x > 0 else "-∞"
    # ICU formats the shortest round-trip decimal of a double ("1.005"), not its exact binary
    # value, so 1.005 -> "1.01" here while (1.005).toFixed(2) is "1.00".
    d = Decimal(repr(float(x))) if isinstance(x, float) else Decimal(x)
    neg = d.is_signed()
    q = abs(d).quantize(Decimal(1).scaleb(-max_frac), rounding=ROUND_HALF_UP, context=_CTX)
    s = f"{q:.{max_frac}f}"
    if "." in s:
        int_part, frac_part = s.split(".")
    else:
        int_part, frac_part = s, ""
    frac_part = frac_part.rstrip("0")
    if len(frac_part) < min_frac:
        frac_part = frac_part + "0" * (min_frac - len(frac_part))
    if grouping:
        int_part = f"{int(int_part):,}"
    out = int_part + (f".{frac_part}" if frac_part else "")
    return f"-{out}" if neg else out


def intl_usd(x: float, frac: int) -> str:
    """`Intl.NumberFormat("en-US", {style: "currency", currency: "USD", min=max=frac})`."""
    body = intl_number(x, frac, frac)
    if body.startswith("-"):
        return f"-${body[1:]}"
    return f"${body}"


# ---------------------------------------------------------------------------
# Dates

_ISO_DATE_ONLY = re.compile(r"[+-]?\d{4,6}(?:-\d{2}(?:-\d{2})?)?")


def parse_iso_ms(value: str | None) -> int | None:
    """`Date.parse` for ISO 8601 strings; None stands for NaN.

    Date-only forms are UTC; date-time forms without an offset are local time (as in JS).
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if _ISO_DATE_ONLY.fullmatch(s):
            parts = s.split("-")
            if s.startswith(("+", "-")):
                return None
            y = int(parts[0])
            mo = int(parts[1]) if len(parts) > 1 else 1
            d = int(parts[2]) if len(parts) > 2 else 1
            return int((datetime(y, mo, d, tzinfo=timezone.utc) - _EPOCH) / timedelta(milliseconds=1))
        if not re.match(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", s):
            return None
        t = s
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        # Python accepts up to 6 fractional digits; JS truncates extra precision.
        t = re.sub(r"(\.\d{6})\d+", r"\1", t)
        dt = datetime.fromisoformat(t)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # local time, like JS
    return math.floor((dt - _EPOCH) / timedelta(milliseconds=1))


def iso_from_ms(ms: float) -> str:
    """`new Date(ms).toISOString()`: "YYYY-MM-DDTHH:MM:SS.mmmZ"."""
    dt = _EPOCH + timedelta(milliseconds=int(ms))
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_from_ms(ms: float) -> datetime:
    return _EPOCH + timedelta(milliseconds=int(ms))


def date_utc(year: int, month0: int, day: int = 1) -> int:
    """`Date.UTC(year, month0, day)` with month overflow normalisation."""
    year += month0 // 12
    month0 %= 12
    base = datetime(year, month0 + 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
    return int((base - _EPOCH) / timedelta(milliseconds=1))


def now_iso() -> str:
    return iso_from_ms(now_ms())


def now_ms() -> int:
    return int((datetime.now(timezone.utc) - _EPOCH) / timedelta(milliseconds=1))


# ---------------------------------------------------------------------------
# Strings


def encode_uri_component(s: str) -> str:
    """`encodeURIComponent`."""
    return quote(s, safe="!*'()~")


# ICU root collation order (non-ignorable) for ASCII punctuation and symbols.
_PUNCT_ORDER = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_PUNCT_WEIGHT = {c: i for i, c in enumerate(_PUNCT_ORDER)}


def _collation_key(s: str) -> tuple[tuple, tuple, tuple]:
    primary: list[tuple[int, int]] = []
    secondary: list[int] = []
    tertiary: list[int] = []
    for ch in s:
        decomposed = unicodedata.normalize("NFD", ch)
        base = decomposed[0]
        accent = sum(ord(c) for c in decomposed[1:] if unicodedata.category(c) == "Mn")
        if base.isspace():
            weight = (0, ord(base))
        elif base.isdigit():
            weight = (3, ord(base))
        elif base.isalpha():
            weight = (4, ord(base.lower()))
        elif base in _PUNCT_WEIGHT:
            weight = (1, _PUNCT_WEIGHT[base])
        else:
            weight = (2, ord(base))
        primary.append(weight)
        secondary.append(accent)
        tertiary.append(1 if base.isupper() else 0)
    return tuple(primary), tuple(secondary), tuple(tertiary)


def locale_compare(a: str, b: str) -> int:
    """Approximation of `a.localeCompare(b)` (ICU root collation): punctuation < digits <
    letters, case-insensitive first, accents second, lowercase before uppercase last."""
    if a == b:
        return 0
    ka, kb = _collation_key(a), _collation_key(b)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


def first_nonzero(*values: float) -> float:
    """`a || b || c` over comparator results (NaN and 0 fall through)."""
    for v in values:
        if v and not (isinstance(v, float) and math.isnan(v)):
            return v
    return 0
