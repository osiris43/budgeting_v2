from datetime import date

from datetime import datetime
from datetime import timedelta

from flask import Blueprint, abort, redirect, render_template, request
import plotly.graph_objects as go

from . import db
from .models import Account, Category, MerchantRule, StatementImport, Transaction
from .services.normalization import extract_detail, extract_merchant, normalize_description

bp = Blueprint("main", __name__)


def _analysis_transfer_category_ids(*, include_transfers: bool) -> set[int]:
    if include_transfers:
        return set()

    categories_all = db.session.execute(db.select(Category)).scalars().all()
    by_parent: dict[int | None, list[Category]] = {}
    for c in categories_all:
        by_parent.setdefault(c.parent_id, []).append(c)

    transfer_ids: set[int] = set()
    transfer_roots = [c for c in categories_all if (c.name or "").strip().lower() == "transfer"]
    stack = [c.id for c in transfer_roots]
    while stack:
        cid = stack.pop()
        if cid in transfer_ids:
            continue
        transfer_ids.add(cid)
        for child in by_parent.get(cid, []):
            stack.append(child.id)
    return transfer_ids


@bp.get("/")
def home():
    accounts_count = db.session.execute(db.select(db.func.count(Account.id))).scalar_one()
    uncategorized_count = db.session.execute(
        db.select(db.func.count(Transaction.id)).where(Transaction.category_id.is_(None))
    ).scalar_one()

    today = date.today()
    month_start = today.replace(day=1)
    month_spend_cents = (
        db.session.execute(
            db.select(db.func.coalesce(db.func.sum(Transaction.amount_cents), 0)).where(
                Transaction.posted_date >= month_start,
                Transaction.amount_cents > 0,
            )
        ).scalar_one()
        or 0
    )

    return render_template(
        "home.html",
        accounts_count=accounts_count,
        uncategorized_count=uncategorized_count,
        month_spend_cents=month_spend_cents,
    )


@bp.get("/accounts")
def accounts_list():
    accounts = db.session.execute(db.select(Account).order_by(Account.institution, Account.name)).scalars().all()
    return render_template("accounts.html", accounts=accounts)


@bp.get("/accounts/<int:account_id>")
def account_detail(account_id: int):
    account = db.session.get(Account, account_id)
    if not account:
        abort(404)

    recent = (
        db.session.execute(
            db.select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )

    total_spend_cents = (
        db.session.execute(
            db.select(db.func.coalesce(db.func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.amount_cents > 0,
            )
        ).scalar_one()
        or 0
    )

    total_credits_cents = (
        db.session.execute(
            db.select(db.func.coalesce(db.func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.amount_cents < 0,
            )
        ).scalar_one()
        or 0
    )

    uncategorized_count = db.session.execute(
        db.select(db.func.count(Transaction.id)).where(
            Transaction.account_id == account_id,
            Transaction.category_id.is_(None),
        )
    ).scalar_one()

    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()

    return render_template(
        "account_detail.html",
        account=account,
        recent=recent,
        total_spend_cents=total_spend_cents,
        total_credits_cents=total_credits_cents,
        uncategorized_count=uncategorized_count,
        categories=categories,
    )


@bp.get("/accounts/<int:account_id>/transactions")
def account_transactions(account_id: int):
    account = db.session.get(Account, account_id)
    if not account:
        abort(404)

    sort = (request.args.get("sort") or "date").strip().lower()
    direction = (request.args.get("dir") or "desc").strip().lower()

    if direction not in ("asc", "desc"):
        direction = "desc"

    order_col = Transaction.posted_date
    if sort == "amount":
        order_col = Transaction.amount_cents
    elif sort == "merchant":
        order_col = Transaction.merchant
    elif sort == "description":
        order_col = Transaction.description_raw
    elif sort == "category":
        # Category sort handled with outer join.
        order_col = Category.name

    stmt = db.select(Transaction).where(Transaction.account_id == account_id)

    if sort == "category":
        stmt = stmt.join(Category, Transaction.category_id == Category.id, isouter=True)

    if direction == "asc":
        stmt = stmt.order_by(order_col.asc(), Transaction.id.asc())
    else:
        stmt = stmt.order_by(order_col.desc(), Transaction.id.desc())

    txs = db.session.execute(stmt.limit(1000)).scalars().all()
    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()

    return render_template(
        "account_transactions.html",
        account=account,
        txs=txs,
        categories=categories,
        sort=sort,
        direction=direction,
    )


@bp.get("/transactions/<int:tx_id>/edit")
def transaction_edit(tx_id: int):
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        abort(404)

    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()
    next_url = (request.args.get("next") or "").strip()
    return render_template("transaction_edit.html", tx=tx, categories=categories, next_url=next_url)


@bp.post("/transactions/<int:tx_id>/edit")
def transaction_edit_post(tx_id: int):
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        abort(404)

    description_raw = (request.form.get("description_raw") or "").strip()
    category_id_s = (request.form.get("category_id") or "").strip()
    next_url = (request.form.get("next_url") or "").strip()

    if not description_raw:
        abort(400)

    if category_id_s:
        try:
            category_id = int(category_id_s)
        except ValueError:
            abort(400)
        category = db.session.get(Category, category_id)
        if not category:
            abort(400)
        tx.category_id = category.id
        tx.category_source = "manual"
    else:
        tx.category_id = None
        tx.category_source = "unknown"

    tx.description_raw = description_raw
    desc_clean = normalize_description(description_raw)
    merchant = extract_merchant(desc_clean)
    tx.merchant = merchant or None
    tx.description_clean = extract_detail(desc_clean, merchant) if merchant else desc_clean

    db.session.commit()

    if next_url:
        return redirect(next_url)
    return redirect(f"/accounts/{tx.account_id}/transactions")


@bp.post("/transactions/<int:tx_id>/set-category")
def set_transaction_category(tx_id: int):
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        abort(404)

    category_id_s = (request.form.get("category_id") or "").strip()
    if not category_id_s:
        tx.category_id = None
        tx.category_source = "unknown"
        db.session.commit()
        return {
            "ok": True,
            "tx_id": tx.id,
            "category_id": None,
            "category_name": "",
            "category_source": tx.category_source,
        }

    try:
        category_id = int(category_id_s)
    except ValueError:
        abort(400)

    category = db.session.get(Category, category_id)
    if not category:
        abort(400)

    tx.category_id = category.id
    tx.category_source = "manual"
    db.session.commit()

    return {
        "ok": True,
        "tx_id": tx.id,
        "category_id": tx.category_id,
        "category_name": category.name,
        "category_source": tx.category_source,
    }


@bp.get("/imports")
def imports_list():
    imports = (
        db.session.execute(
            db.select(StatementImport).order_by(StatementImport.imported_at.desc(), StatementImport.id.desc())
        )
        .scalars()
        .all()
    )
    return render_template("imports.html", imports=imports)


@bp.get("/categories")
def categories_list():
    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()
    return render_template("categories.html", categories=categories)


@bp.post("/categories/create")
def create_category():
    name = (request.form.get("name") or "").strip()
    parent_id_s = (request.form.get("parent_id") or "").strip()

    if not name:
        abort(400)

    parent_id = int(parent_id_s) if parent_id_s else None
    parent = db.session.get(Category, parent_id) if parent_id else None

    existing = db.session.execute(db.select(Category).where(Category.name == name)).scalar_one_or_none()
    if existing:
        return redirect("/categories")

    cat = Category(name=name, parent_id=parent.id if parent else None)
    db.session.add(cat)
    db.session.commit()
    return redirect("/categories")


@bp.get("/imports/<int:import_id>")
def import_detail(import_id: int):
    imp = db.session.get(StatementImport, import_id)
    if not imp:
        abort(404)

    confirm_delete = (request.args.get("delete") or "").strip() == "1"

    txs = (
        db.session.execute(
            db.select(Transaction)
            .where(Transaction.statement_import_id == import_id)
            .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        )
        .scalars()
        .all()
    )

    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()
    return render_template(
        "import_detail.html",
        imp=imp,
        txs=txs,
        categories=categories,
        confirm_delete=confirm_delete,
    )


@bp.post("/imports/<int:import_id>/delete")
def delete_import(import_id: int):
    imp = db.session.get(StatementImport, import_id)
    if not imp:
        abort(404)

    confirmed = (request.form.get("confirmed") or "").strip().lower() == "yes"
    if not confirmed:
        return redirect(f"/imports/{import_id}?delete=1")

    db.session.execute(db.delete(Transaction).where(Transaction.statement_import_id == import_id))
    db.session.delete(imp)
    db.session.commit()
    return redirect("/imports")


@bp.post("/imports/<int:import_id>/confirm")
def confirm_import(import_id: int):
    imp = db.session.get(StatementImport, import_id)
    if not imp:
        abort(404)

    imp.status = "confirmed"
    imp.confirmed_at = datetime.utcnow()
    db.session.commit()
    return redirect(f"/imports/{import_id}/promote-rules")


@bp.get("/imports/<int:import_id>/promote-rules")
def promote_rules(import_id: int):
    imp = db.session.get(StatementImport, import_id)
    if not imp:
        abort(404)

    # Find unique merchant+category pairs from model-categorized transactions
    model_txs = (
        db.session.execute(
            db.select(
                Transaction.merchant,
                Transaction.category_id,
                Category.name.label("category_name"),
                db.func.count(Transaction.id).label("tx_count"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.statement_import_id == import_id,
                Transaction.category_source == "model",
                Transaction.merchant.isnot(None),
                Transaction.merchant != "",
            )
            .group_by(Transaction.merchant, Transaction.category_id, Category.name)
            .order_by(Transaction.merchant)
        )
        .all()
    )

    # Exclude merchants that already have a matching rule (with no detail_pattern)
    promotable = []
    for row in model_txs:
        existing = db.session.execute(
            db.select(MerchantRule).where(
                MerchantRule.pattern == row.merchant,
                MerchantRule.detail_pattern.is_(None),
            )
        ).scalar_one_or_none()
        if not existing:
            promotable.append(row)

    if not promotable:
        return redirect("/imports")

    return render_template(
        "promote_rules.html",
        imp=imp,
        promotable=promotable,
    )


@bp.post("/imports/<int:import_id>/promote-rules")
def promote_rules_post(import_id: int):
    imp = db.session.get(StatementImport, import_id)
    if not imp:
        abort(404)

    # Process each checked merchant row
    idx = 0
    while True:
        merchant = request.form.get(f"merchant_{idx}")
        if merchant is None:
            break

        checked = request.form.get(f"checked_{idx}") == "on"
        if checked:
            category_id_s = request.form.get(f"category_id_{idx}", "")
            detail_pattern = (request.form.get(f"detail_pattern_{idx}") or "").strip() or None

            if category_id_s:
                category_id = int(category_id_s)
                # Avoid duplicates
                existing = db.session.execute(
                    db.select(MerchantRule).where(
                        MerchantRule.pattern == merchant,
                        MerchantRule.detail_pattern == detail_pattern
                        if detail_pattern
                        else MerchantRule.detail_pattern.is_(None),
                    )
                ).scalar_one_or_none()
                if not existing:
                    db.session.add(MerchantRule(
                        pattern=merchant,
                        category_id=category_id,
                        detail_pattern=detail_pattern,
                    ))

        idx += 1

    db.session.commit()
    return redirect("/imports")


@bp.post("/imports/<int:import_id>/transactions/<int:tx_id>/set-category")
def set_import_transaction_category(import_id: int, tx_id: int):
    tx = db.session.get(Transaction, tx_id)
    if not tx or tx.statement_import_id != import_id:
        abort(404)

    category_id_s = request.form.get("category_id")
    if not category_id_s:
        abort(400)

    category = db.session.get(Category, int(category_id_s))
    if not category:
        abort(400)

    create_rule = request.form.get("create_rule") == "on"

    tx.category_id = category.id
    tx.category_source = "manual"

    if create_rule and tx.merchant:
        existing = db.session.execute(
            db.select(MerchantRule).where(MerchantRule.pattern == tx.merchant)
        ).scalar_one_or_none()
        if existing:
            existing.category_id = category.id
        else:
            db.session.add(MerchantRule(pattern=tx.merchant, category_id=category.id))

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return {
            "ok": True,
            "tx_id": tx.id,
            "category_id": tx.category_id,
            "category_name": category.name,
            "category_source": tx.category_source,
        }

    return redirect(f"/imports/{import_id}")


@bp.post("/imports/<int:import_id>/categories/create")
def create_category_for_import(import_id: int):
    name = (request.form.get("name") or "").strip()
    parent_id_s = (request.form.get("parent_id") or "").strip()

    if not name:
        abort(400)

    parent_id = int(parent_id_s) if parent_id_s else None
    parent = db.session.get(Category, parent_id) if parent_id else None

    existing = db.session.execute(db.select(Category).where(Category.name == name)).scalar_one_or_none()
    if existing:
        return redirect(f"/imports/{import_id}")

    cat = Category(name=name, parent_id=parent.id if parent else None)
    db.session.add(cat)
    db.session.commit()
    return redirect(f"/imports/{import_id}")


@bp.get("/analysis/spend")
def analysis_spend():
    granularity = (request.args.get("granularity") or "month").lower()
    account_id_s = (request.args.get("account_id") or "").strip()
    days_s = (request.args.get("days") or "365").strip()
    include_category_ids_s = request.args.getlist("include_category_id")
    exclude_category_ids_s = request.args.getlist("exclude_category_id")
    include_transfers = (request.args.get("include_transfers") or "").strip() == "1"

    try:
        days = int(days_s)
    except ValueError:
        days = 365

    if granularity not in ("day", "month"):
        granularity = "month"

    account_id = int(account_id_s) if account_id_s else None

    def _to_int_list(values: list[str]) -> list[int]:
        out: list[int] = []
        for v in values:
            v = (v or "").strip()
            if not v:
                continue
            try:
                out.append(int(v))
            except ValueError:
                continue
        return out

    include_category_ids = _to_int_list(include_category_ids_s)
    exclude_category_ids = _to_int_list(exclude_category_ids_s)

    # By default, exclude transfers (e.g. paying off credit cards, moving money between accounts).
    # This avoids double counting spend across accounts.
    transfer_category_ids = _analysis_transfer_category_ids(include_transfers=include_transfers)

    end = date.today()
    start = end - timedelta(days=days)

    if granularity == "day":
        period_expr = db.func.strftime("%Y-%m-%d", Transaction.posted_date)
    else:
        period_expr = db.func.strftime("%Y-%m", Transaction.posted_date)

    stmt = (
        db.select(
            period_expr.label("period"),
            db.func.coalesce(db.func.sum(Transaction.amount_cents), 0).label("spend_cents"),
        )
        .where(
            Transaction.posted_date >= start,
            Transaction.posted_date <= end,
            Transaction.amount_cents > 0,
        )
        .group_by("period")
        .order_by("period")
    )

    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)

    if include_category_ids:
        stmt = stmt.where(Transaction.category_id.in_(include_category_ids))
    elif exclude_category_ids:
        stmt = stmt.where(~Transaction.category_id.in_(exclude_category_ids))

    if transfer_category_ids:
        stmt = stmt.where(~Transaction.category_id.in_(sorted(transfer_category_ids)))

    rows = db.session.execute(stmt).all()
    x = [r.period for r in rows]
    y = [(r.spend_cents or 0) / 100 for r in rows]

    fig = go.Figure(
        data=[go.Bar(x=x, y=y, marker_color="#6366f1")],
        layout=go.Layout(
            title="Spend over time",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0"),
            xaxis=(
                dict(title="Period", type="category")
                if granularity == "month"
                else dict(title="Period")
            ),
            yaxis=dict(title="Spend (USD)"),
            margin=dict(l=40, r=20, t=50, b=40),
        ),
    )

    cat_stmt = (
        db.select(
            Category.name.label("category"),
            db.func.coalesce(db.func.sum(Transaction.amount_cents), 0).label("spend_cents"),
        )
        .select_from(Transaction)
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.posted_date >= start,
            Transaction.posted_date <= end,
            Transaction.amount_cents > 0,
        )
        .group_by(Category.name)
        .order_by(db.text("spend_cents DESC"))
        .limit(10)
    )

    if account_id is not None:
        cat_stmt = cat_stmt.where(Transaction.account_id == account_id)

    if include_category_ids:
        cat_stmt = cat_stmt.where(Transaction.category_id.in_(include_category_ids))
    elif exclude_category_ids:
        cat_stmt = cat_stmt.where(~Transaction.category_id.in_(exclude_category_ids))

    if transfer_category_ids:
        cat_stmt = cat_stmt.where(~Transaction.category_id.in_(sorted(transfer_category_ids)))

    cat_rows = db.session.execute(cat_stmt).all()
    cat_labels = [r.category for r in cat_rows]
    cat_values = [(r.spend_cents or 0) / 100 for r in cat_rows]

    fig_cats = go.Figure(
        data=[go.Pie(labels=cat_labels, values=cat_values, hole=0.45)],
        layout=go.Layout(
            title="Top categories (top 10)",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0"),
            margin=dict(l=20, r=20, t=50, b=20),
            legend=dict(orientation="h"),
        ),
    )

    accounts = db.session.execute(db.select(Account).order_by(Account.institution, Account.name)).scalars().all()
    categories = db.session.execute(db.select(Category).order_by(Category.name)).scalars().all()

    return render_template(
        "analysis_spend.html",
        fig_json=fig.to_json(),
        fig_cats_json=fig_cats.to_json(),
        granularity=granularity,
        account_id=account_id,
        days=days,
        accounts=accounts,
        categories=categories,
        include_category_ids=include_category_ids,
        exclude_category_ids=exclude_category_ids,
        include_transfers=include_transfers,
    )


@bp.get("/analysis/spend/transactions.json")
def analysis_spend_transactions_json():
    account_id_s = (request.args.get("account_id") or "").strip()
    days_s = (request.args.get("days") or "365").strip()
    include_category_ids_s = request.args.getlist("include_category_id")
    exclude_category_ids_s = request.args.getlist("exclude_category_id")
    include_transfers = (request.args.get("include_transfers") or "").strip() == "1"
    include_income = (request.args.get("include_income") or "").strip() == "1"
    tx_category_id_s = (request.args.get("tx_category_id") or "").strip()
    page_s = (request.args.get("page") or "1").strip()
    page_size_s = (request.args.get("page_size") or "20").strip()

    try:
        days = int(days_s)
    except ValueError:
        days = 365

    account_id = int(account_id_s) if account_id_s else None

    def _to_int_list(values: list[str]) -> list[int]:
        out: list[int] = []
        for v in values:
            v = (v or "").strip()
            if not v:
                continue
            try:
                out.append(int(v))
            except ValueError:
                continue
        return out

    include_category_ids = _to_int_list(include_category_ids_s)
    exclude_category_ids = _to_int_list(exclude_category_ids_s)

    tx_category_id: int | None
    if tx_category_id_s:
        try:
            tx_category_id = int(tx_category_id_s)
        except ValueError:
            tx_category_id = None
    else:
        tx_category_id = None

    try:
        page = int(page_s)
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    try:
        page_size = int(page_size_s)
    except ValueError:
        page_size = 20
    if page_size <= 0:
        page_size = 20
    if page_size > 200:
        page_size = 200

    end = date.today()
    start = end - timedelta(days=days)

    transfer_category_ids = _analysis_transfer_category_ids(include_transfers=include_transfers)

    base_where = [
        Transaction.posted_date >= start,
        Transaction.posted_date <= end,
    ]
    if include_income:
        base_where.append(Transaction.amount_cents != 0)
    else:
        base_where.append(Transaction.amount_cents > 0)
    if account_id is not None:
        base_where.append(Transaction.account_id == account_id)

    if include_category_ids:
        base_where.append(Transaction.category_id.in_(include_category_ids))
    elif exclude_category_ids:
        base_where.append(~Transaction.category_id.in_(exclude_category_ids))

    if transfer_category_ids:
        base_where.append(~Transaction.category_id.in_(sorted(transfer_category_ids)))

    if tx_category_id is not None:
        base_where.append(Transaction.category_id == tx_category_id)

    total = (
        db.session.execute(db.select(db.func.count(Transaction.id)).where(*base_where)).scalar_one()
        or 0
    )

    stmt = (
        db.select(Transaction, Category.name.label("category_name"))
        .select_from(Transaction)
        .join(Category, Transaction.category_id == Category.id, isouter=True)
        .where(*base_where)
        .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )

    rows = db.session.execute(stmt).all()
    out_rows: list[dict] = []
    for tx, category_name in rows:
        out_rows.append(
            {
                "id": tx.id,
                "posted_date": tx.posted_date.isoformat() if tx.posted_date else "",
                "amount": (tx.amount_cents or 0) / 100,
                "merchant": tx.merchant or "",
                "description": tx.description_clean or tx.description_raw or "",
                "category_id": tx.category_id,
                "category": category_name or "",
            }
        )

    return {
        "ok": True,
        "page": page,
        "page_size": page_size,
        "total": total,
        "rows": out_rows,
    }
