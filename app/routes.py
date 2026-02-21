from datetime import date

from datetime import datetime
from datetime import timedelta

from flask import Blueprint, abort, redirect, render_template, request
import plotly.graph_objects as go

from . import db
from .models import Account, Category, MerchantRule, StatementImport, Transaction

bp = Blueprint("main", __name__)


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

    return render_template(
        "account_detail.html",
        account=account,
        recent=recent,
        total_spend_cents=total_spend_cents,
        total_credits_cents=total_credits_cents,
        uncategorized_count=uncategorized_count,
    )


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
    return redirect(f"/imports/{import_id}")


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

    try:
        days = int(days_s)
    except ValueError:
        days = 365

    if granularity not in ("day", "month"):
        granularity = "month"

    account_id = int(account_id_s) if account_id_s else None

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
            xaxis=dict(title="Period"),
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

    return render_template(
        "analysis_spend.html",
        fig_json=fig.to_json(),
        fig_cats_json=fig_cats.to_json(),
        granularity=granularity,
        account_id=account_id,
        days=days,
        accounts=accounts,
    )
