import os

from typing import Optional

from .. import db
from ..models import Category, MerchantRule, Transaction
from .normalization import extract_merchant, normalize_description
from .ollama_client import categorize_with_ollama


def apply_rules(*, merchant: Optional[str], description_clean: str) -> Optional[Category]:
    rules = db.session.execute(db.select(MerchantRule)).scalars().all()
    haystack = f"{merchant or ''} {description_clean}".upper()

    for rule in rules:
        if rule.pattern.upper() in haystack:
            return db.session.get(Category, rule.category_id)

    return None


def get_allowed_categories() -> list[str]:
    cats = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()
    return [c.name for c in cats]


def _canonicalize_category_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def _map_model_category(model_category: str, allowed: list[str]) -> Optional[str]:
    mc = _canonicalize_category_name(model_category)
    if not mc:
        return None

    # Exact / case-insensitive match
    for a in allowed:
        if a.lower() == mc.lower():
            return a

    # Common synonym mapping (expand over time)
    synonyms = {
        "health": "Medical",
        "healthcare": "Medical",
        "medical": "Medical",
        "restaurants": "Dining",
        "restaurant": "Dining",
        "food": "Dining",
        "groceries": "Groceries",
        "subscription": "Subscriptions",
        "subscriptions": "Subscriptions",
        "internet": "Internet",
        "utilities": "Utilities",
        "rent": "Rent/Mortgage",
        "mortgage": "Rent/Mortgage",
        "insurance": "Insurance",
        "transfer": "Transfer",
        "income": "Income",
    }

    mapped = synonyms.get(mc.lower())
    if mapped:
        for a in allowed:
            if a.lower() == mapped.lower():
                return a

    return None


def categorize_transactions(
    *,
    account_id: Optional[int] = None,
    limit: int = 200,
    dry_run: bool = False,
    create_rules: bool = False,
    auto_create_categories: bool = False,
) -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL")
    if not model:
        raise RuntimeError("Missing required environment variable: OLLAMA_MODEL")

    allowed = get_allowed_categories()
    if not allowed:
        raise RuntimeError("No categories in database. Run `flask init-default-categories` first.")

    stmt = db.select(Transaction).where(Transaction.category_id.is_(None))
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)

    stmt = stmt.order_by(Transaction.posted_date.desc(), Transaction.id.desc()).limit(limit)

    txs = db.session.execute(stmt).scalars().all()

    categorized = 0
    ruled = 0
    modeled = 0
    skipped = 0
    created_categories = 0

    for tx in txs:
        desc_clean = normalize_description(tx.description_raw)
        merch = extract_merchant(desc_clean)

        allowed_for_tx = list(allowed)

        # Guardrails based on our sign convention:
        # - positive amount_cents => expense
        # - negative amount_cents => credit/refund/payment
        if tx.amount_cents > 0:
            allowed_for_tx = [c for c in allowed_for_tx if c.lower() != "income"]
        if tx.amount_cents < 0:
            # Credits are rarely "Groceries" etc; but we keep allowed wide for now.
            pass

        chosen: Optional[Category] = apply_rules(merchant=merch, description_clean=desc_clean)
        source = None

        if chosen:
            source = "rule"
            ruled += 1
        else:
            model_cat = categorize_with_ollama(
                base_url=base_url,
                model=model,
                description=desc_clean,
                merchant=merch,
                amount_cents=tx.amount_cents,
                bank_category_raw=tx.bank_category_raw,
                categories=allowed_for_tx,
            )

            cat_name = _map_model_category(model_cat, allowed_for_tx)

            if cat_name is None and auto_create_categories:
                cat_name = _canonicalize_category_name(model_cat)
                if cat_name:
                    existing = db.session.execute(
                        db.select(Category).where(Category.name.ilike(cat_name))
                    ).scalar_one_or_none()
                    if existing:
                        chosen = existing
                    else:
                        chosen = Category(name=cat_name)
                        if not dry_run:
                            db.session.add(chosen)
                            db.session.flush()
                        created_categories += 1

                    allowed.append(chosen.name)
                    allowed_for_tx.append(chosen.name)

            if chosen is None and cat_name is not None:
                chosen = db.session.execute(db.select(Category).where(Category.name == cat_name)).scalar_one_or_none()

            if chosen is None:
                skipped += 1
                continue

            source = "model"
            modeled += 1

        if not chosen:
            skipped += 1
            continue

        categorized += 1

        if not dry_run:
            tx.description_clean = desc_clean
            tx.merchant = merch
            tx.category_id = chosen.id
            tx.category_source = source or "unknown"

            if create_rules and merch:
                existing = db.session.execute(
                    db.select(MerchantRule).where(MerchantRule.pattern == merch)
                ).scalar_one_or_none()
                if not existing:
                    db.session.add(MerchantRule(pattern=merch, category_id=chosen.id))

    if not dry_run:
        db.session.commit()

    return {
        "found": len(txs),
        "categorized": categorized,
        "ruled": ruled,
        "modeled": modeled,
        "skipped": skipped,
        "created_categories": created_categories,
        "dry_run": dry_run,
    }
