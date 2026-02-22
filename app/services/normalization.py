import re


_space_re = re.compile(r"\s+")
_trailing_ref_re = re.compile(r"\s*\*[0-9]{3,}\s*$")
_leading_ref_re = re.compile(r"^\s*[0-9A-Z]{10,}\s+")
_sams_re = re.compile(r"^SAM'?S\s+CLUB\b")
_anbtx_prefix_re = re.compile(r"^(EXTERNAL\s+(DEPOSIT|WITHDRAWAL)\b\s*)")
_check_prefix_re = re.compile(r"^(OVER\s+COUNTER\s+CHECK|CHECK\s*-\s*ITEM\s+PROCESSING|CHECK)\b\s*", re.IGNORECASE)


def normalize_description(description: str) -> str:
    s = (description or "").strip()
    s = s.replace("\u00a0", " ")
    s = _space_re.sub(" ", s)
    return s


def extract_merchant(description_clean: str) -> str:
    s = normalize_description(description_clean).upper()

    # Remove leading statement reference numbers like: "8521333D701012T4L SAM'S CLUB ..."
    s = _leading_ref_re.sub("", s)

    # ANBTX export descriptions often start with unhelpful boilerplate prefixes.
    s = _anbtx_prefix_re.sub("", s).strip()

    # Checks are generally not categorizable; keep details in description but make merchant consistent.
    if _check_prefix_re.match(s):
        return "CHECK"

    if _sams_re.match(s):
        return "SAM'S CLUB"

    # Remove common trailing reference numbers like: "ALERT 360 *040410443"
    s = _trailing_ref_re.sub("", s)

    if "*" in s:
        left, right = s.split("*", 1)
        left = left.strip()
        right = right.strip()

        # If the left side looks like a payment processor prefix, take the merchant on the right.
        if len(left) <= 8 and left.replace(" ", "").isalpha():
            if right:
                s = right
        else:
            s = left

    s = _space_re.sub(" ", s).strip()

    # Light cleanup
    s = s.replace(".COM", "")
    s = s.replace("  ", " ")
    return s.strip()


def extract_detail(description_clean: str, merchant: str) -> str:
    s = normalize_description(description_clean)
    if not merchant:
        return s

    s_up = s.upper()
    merch_up = merchant.upper().strip()

    if s_up.startswith(merch_up):
        remainder = s[len(merchant) :].strip()
    else:
        idx = s_up.find(merch_up)
        if idx == -1:
            return s
        remainder = s[idx + len(merchant) :].strip()

    if merch_up in ("SAM'S CLUB", "SAMS CLUB"):
        if "," in remainder:
            remainder = remainder.split(",", 1)[1].strip()
        else:
            remainder = remainder.strip(" -")
    else:
        remainder = remainder.lstrip("-:|, ")

    return normalize_description(remainder) or s
