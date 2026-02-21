import re


_space_re = re.compile(r"\s+")
_trailing_ref_re = re.compile(r"\s*\*[0-9]{3,}\s*$")


def normalize_description(description: str) -> str:
    s = (description or "").strip()
    s = s.replace("\u00a0", " ")
    s = _space_re.sub(" ", s)
    return s


def extract_merchant(description_clean: str) -> str:
    s = normalize_description(description_clean).upper()

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
