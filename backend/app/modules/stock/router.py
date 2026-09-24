from uuid import UUID

from fastapi import APIRouter, Depends, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ListParams,
    envelope,
    get_current_user,
    get_db_session,
    list_params,
    require_permission,
)
from app.modules.auth.models import User
from app.modules.stock.schemas import (
    ProductCreate,
    ProductUpdate,
    PurchaseReturnRequest,
    QuickStockOperationRequest,
    StockAdjustmentRequest,
    StockDamageRequest,
    StockInRequest,
    StockInUpdateRequest,
)
from app.modules.stock.service import (
    ProductService,
    StockOperationService,
)
from app.shared.pagination.params import list_meta

products_router = APIRouter(tags=["products"])
router = APIRouter(prefix="/stock", tags=["stock"])


# ---------------------------------------------------------------- products


@products_router.get("/products")
async def list_products(
    params: ListParams = Depends(list_params),
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> dict:
    service = ProductService(db)
    products, total = await service.list(
        q=params.q,
        category_id=category_id,
        brand_id=brand_id,
        status=params.status,
        page=params.page,
        limit=params.limit,
        sort=params.sort,
    )
    return envelope(products, {"page": params.page, "limit": params.limit, "total": total})


@products_router.post("/products", status_code=http_status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("product.create")),
) -> dict:
    service = ProductService(db)
    return envelope(await service.create(payload))


@products_router.get("/products/{product_id}")
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> dict:
    service = ProductService(db)
    return envelope(await service.get(product_id))


@products_router.patch("/products/{product_id}")
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("product.update")),
) -> dict:
    service = ProductService(db)
    return envelope(await service.update(product_id, payload, actor=actor))


@products_router.delete("/products/{product_id}")
async def delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("product.delete")),
) -> dict:
    service = ProductService(db)
    await service.delete(product_id)
    return envelope({"message": "Product deleted"})


@router.get("/products/{product_id}/cost-history")
async def product_cost_history(
    product_id: UUID,
    params: ListParams = Depends(list_params),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.view")),
) -> dict:
    """Read-only Cost Price history: confirmed Stock In lots, versioned
    oldest → newest and returned newest first. No write path exists."""
    from app.modules.stock import cost_history as cost_history_service

    rows, total = await cost_history_service.product_cost_history(
        db,
        product_id=product_id,
        q=params.q,
        start=params.start_date,
        end=params.end_date,
        page=params.page,
        limit=params.limit,
    )
    return envelope(rows, list_meta(params.page, params.limit, total))


# ------------------------------------------------------- stock operations


@router.get("/operations")
async def list_stock_operations(
    params: ListParams = Depends(list_params),
    type: str = Query(default="STOCK_IN"),
    supplier_id: UUID | None = Query(default=None, alias="supplierId"),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.view")),
) -> dict:
    """Stock operation documents (Stock In / purchase list read model)."""
    from sqlalchemy import select

    from app.modules.suppliers.models import Supplier

    service = StockOperationService(db)
    transactions, total = await service.list_operations(
        q=params.q,
        operation_type=(type or "STOCK_IN").upper(),
        supplier_id=supplier_id,
        status=status,
        start=params.start_date,
        end=params.end_date,
        page=params.page,
        limit=params.limit,
    )
    # One IN query instead of a per-row supplier lookup (P3 N+1).
    supplier_ids = {t.supplier_id for t in transactions if t.supplier_id is not None}
    supplier_names: dict = {}
    if supplier_ids:
        result = await db.execute(
            select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids))
        )
        supplier_names = {row_id: name for row_id, name in result.all()}
    rows = [
        service.operation_document_out(transaction, supplier_names.get(transaction.supplier_id))
        for transaction in transactions
    ]
    return envelope(rows, list_meta(params.page, params.limit, total))


@router.post("/operations", status_code=http_status.HTTP_201_CREATED)
async def quick_stock_operation(
    payload: QuickStockOperationRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> dict:
    """Single-product quick operation (Stock In / Adjustment / Damage).
    Permission is chosen by type, mirroring the individual endpoints."""
    from app.core.exceptions import AccessDeniedError
    from app.core.permissions import user_has_permission
    from app.modules.stock.service import StockOperationService

    permission = {
        "stock_in": "stock.in",
        "adjustment": "stock.adjust",
        "damage": "stock.damage",
    }[payload.type]
    if not user_has_permission(actor, permission):
        raise AccessDeniedError("You do not have permission for this operation")
    service = StockOperationService(db)
    return envelope(await service.quick_operation(payload=payload, actor=actor))


@router.post("/in", status_code=http_status.HTTP_201_CREATED)
async def stock_in(
    payload: StockInRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.in")),
) -> dict:
    service = StockOperationService(db)
    result = await service.stock_in(payload, actor=actor)
    return envelope(result)


@router.patch("/in/{stock_transaction_id}")
async def update_stock_in(
    stock_transaction_id: UUID,
    payload: StockInUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.in")),
) -> dict:
    """Edit a confirmed Stock In (reverse the old receipt, apply the new lines)."""
    service = StockOperationService(db)
    result = await service.update_purchase(stock_transaction_id, payload, actor=actor)
    return envelope(result)


@router.post("/in/{stock_transaction_id}/return", status_code=http_status.HTTP_201_CREATED)
async def purchase_return(
    stock_transaction_id: UUID,
    payload: PurchaseReturnRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.in")),
) -> dict:
    """Return to supplier against a confirmed Stock In (spec: Purchase Return
    Transaction). Immutable PRT- document; PURCHASE_RETURN stock out; supplier
    debt reduction / credit; no Stock In edit."""
    service = StockOperationService(db)
    result = await service.purchase_return(stock_transaction_id, payload, actor=actor)
    return envelope(result.model_dump())


@router.post("/adjust", status_code=http_status.HTTP_201_CREATED)
async def stock_adjust(
    payload: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.adjust")),
) -> dict:
    service = StockOperationService(db)
    result = await service.adjust(payload, actor=actor)
    return envelope(result)


@router.post("/damage", status_code=http_status.HTTP_201_CREATED)
async def stock_damage(
    payload: StockDamageRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.damage")),
) -> dict:
    service = StockOperationService(db)
    result = await service.damage(payload, actor=actor)
    return envelope(result)


@router.get("/movements")
async def list_movements(
    params: ListParams = Depends(list_params),
    product_id: UUID | None = Query(default=None),
    movement_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.view")),
) -> dict:
    """Immutable movement ledger (Stock Movements page).

    Filters: q (document no / note), product, movement type, date range,
    plus pagination and `sort` (`createdAt`/`quantity`, `-` = descending).
    Balance before/after is derived from the ledger; rows are read-only.
    """
    service = StockOperationService(db)
    movements, total = await service.list_movements(
        q=params.q,
        product_id=product_id,
        movement_type=movement_type,
        start=params.start_date,
        end=params.end_date,
        page=params.page,
        limit=params.limit,
        sort=params.sort,
    )
    return envelope(movements, list_meta(params.page, params.limit, total))


@router.get("/products/{product_id}/history")
async def product_history(
    product_id: UUID,
    params: ListParams = Depends(list_params),
    type: str = Query(default="all", pattern="^(stock_in|stock_out|damage|all)$"),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.view")),
) -> dict:
    """Compact stock-history rows for the product history dialogs.

    ``type`` maps to the Stock list columns: stock_in | stock_out | damage | all
    (``all`` is the full movement history behind Current Stock).
    """
    from app.core.exceptions import NotFoundError
    from app.modules.stock.history import product_history as fetch_history
    from app.modules.stock.repository import ProductRepository

    if await ProductRepository(db).get(product_id) is None:
        raise NotFoundError("Product not found")
    rows, total = await fetch_history(
        db,
        product_id=product_id,
        kind=type,
        start=params.start_date,
        end=params.end_date,
        page=params.page,
        limit=params.limit,
    )
    return envelope(rows, list_meta(params.page, params.limit, total))


@router.get("/movements/{movement_id}/invoice")
async def movement_invoice(
    movement_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("stock.view")),
) -> dict:
    """Invoice detail behind one SALE movement (Stock Out dialog click-through).

    Read-only: reuses the POS receipt payload (items, totals, payment)
    so the dialog detail matches the invoice exactly.
    """
    from app.modules.stock.history import movement_invoice as fetch_movement_invoice

    return envelope(await fetch_movement_invoice(db, movement_id))
