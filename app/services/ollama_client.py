import json
from typing import Iterable, Optional

import requests


def categorize_with_ollama(
    *,
    base_url: str,
    model: str,
    description: str,
    merchant: Optional[str],
    amount_cents: int,
    bank_category_raw: Optional[str],
    categories: Iterable[str],
) -> str:
    cats = list(categories)
    merchant_part = f"Merchant: {merchant}\n" if merchant else ""
    bank_cat_part = f"Bank category: {bank_category_raw}\n" if bank_category_raw else ""

    amount = amount_cents / 100
    direction = "expense" if amount_cents > 0 else "credit"

    prompt = (
        "You are categorizing a single financial transaction into a personal budget category. "
        "Choose exactly one category from the provided list.\n"
        "Rules:\n"
        "- Use 'Income' ONLY for genuine income/inflows (e.g. paycheck, salary, interest).\n"
        "- Credit card payments, refunds, and payments should NOT be categorized as Income. Prefer 'Transfer' if available.\n"
        "- If the merchant is clearly a utility/subscription/store, categorize accordingly.\n\n"
        f"Amount: {amount:.2f} USD ({direction})\n"
        f"Description: {description}\n"
        f"{merchant_part}"
        f"{bank_cat_part}"
        f"Allowed categories: {cats}\n\n"
        "Return ONLY valid JSON in this exact shape: {\"category\": \"<one of allowed categories>\"}."
    )

    resp = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # Ollama returns generated text in 'response'
    text = (data.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: try to find a category name in the response
        upper = text.upper()
        for c in cats:
            if c.upper() in upper:
                return c
        raise

    category = payload.get("category")
    if not isinstance(category, str) or not category:
        raise RuntimeError("Ollama response JSON missing 'category'")

    # Return raw category; caller can decide whether to map or create new categories.
    return category
