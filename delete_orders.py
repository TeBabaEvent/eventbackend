#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Delete one or more orders and their related data.

What gets deleted (per order):
- scan_logs linked to the order's tickets
- tickets (via ORM cascade)
- order_items (via ORM cascade)
- the order itself

Optional:
- adjust EventPack.sold_count for completed orders

Usage examples:
  python delete_orders.py BABA-ABC123
  python delete_orders.py 8f1e9c2a-1234-5678-9012-abcdefabcdef
  python delete_orders.py BABA-ABC123 BABA-XYZ789 --dry-run
  python delete_orders.py BABA-ABC123 --adjust-sold-count --yes
"""

import sys
import io
from typing import List, Tuple, Dict

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.db.database import SessionLocal
from app.db import models


# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def find_order(db, identifier: str) -> models.Order | None:
    """Find order by id or order_number."""
    return (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items),
            joinedload(models.Order.tickets)
        )
        .filter(or_(models.Order.id == identifier, models.Order.order_number == identifier))
        .first()
    )


def get_pack_quantities(order: models.Order) -> List[Tuple[str, str, int]]:
    """
    Return list of (event_id, pack_id, quantity) for the order.
    Handles both new cart orders (OrderItems) and legacy fields.
    """
    result: List[Tuple[str, str, int]] = []

    if order.items and len(order.items) > 0:
        for item in order.items:
            if not item.pack_id:
                continue
            qty = int(item.quantity or 0)
            if qty <= 0:
                continue
            result.append((item.event_id or order.event_id, item.pack_id, qty))
        return result

    # Legacy single-pack order
    if order.pack_id:
        qty = int(order.quantity or 0)
        if qty > 0:
            result.append((order.event_id, order.pack_id, qty))

    return result


def count_scan_logs(db, ticket_ids: List[str]) -> int:
    if not ticket_ids:
        return 0
    return (
        db.query(models.ScanLog)
        .filter(models.ScanLog.ticket_id.in_(ticket_ids))
        .count()
    )


def delete_scan_logs(db, ticket_ids: List[str]) -> int:
    if not ticket_ids:
        return 0
    return (
        db.query(models.ScanLog)
        .filter(models.ScanLog.ticket_id.in_(ticket_ids))
        .delete(synchronize_session=False)
    )


def adjust_sold_counts(db, order: models.Order) -> Dict[str, int]:
    """
    Decrement EventPack.sold_count for completed orders.
    Returns a summary dict.
    """
    summary = {
        "packs_updated": 0,
        "total_qty": 0,
        "missing_event_packs": 0,
    }

    if order.status != "completed":
        return summary

    for event_id, pack_id, qty in get_pack_quantities(order):
        event_pack = (
            db.query(models.EventPack)
            .filter(models.EventPack.event_id == event_id, models.EventPack.pack_id == pack_id)
            .first()
        )
        if not event_pack:
            summary["missing_event_packs"] += 1
            continue

        before = int(event_pack.sold_count or 0)
        event_pack.sold_count = max(0, before - qty)
        summary["packs_updated"] += 1
        summary["total_qty"] += qty

    return summary


def format_order_summary(order: models.Order, scan_logs_count: int) -> str:
    return (
        f"- {order.order_number} ({order.id}) "
        f"status={order.status} "
        f"items={len(order.items or [])} "
        f"tickets={len(order.tickets or [])} "
        f"scan_logs={scan_logs_count}"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Delete one or more orders and their related data."
    )
    parser.add_argument(
        "identifiers",
        nargs="+",
        help="Order id (UUID) or order_number (BABA-XXXXXX)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without changing the database."
    )
    parser.add_argument(
        "--adjust-sold-count",
        action="store_true",
        help="Decrement EventPack.sold_count for completed orders."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt."
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        orders: Dict[str, models.Order] = {}
        not_found: List[str] = []

        for ident in args.identifiers:
            order = find_order(db, ident)
            if not order:
                not_found.append(ident)
                continue
            orders[order.id] = order

        if not orders:
            print("No orders found for the given identifiers.")
            if not_found:
                print("Not found:", ", ".join(not_found))
            return 1

        print("Orders found:")
        for order in orders.values():
            scan_logs_count = count_scan_logs(db, [t.id for t in order.tickets or []])
            print(format_order_summary(order, scan_logs_count))

        if not_found:
            print("Not found:", ", ".join(not_found))

        if args.dry_run:
            print("\nDry-run: no data was deleted.")
            return 0

        if not args.yes:
            confirm = input("\nType DELETE to confirm: ").strip()
            if confirm != "DELETE":
                print("Cancelled. No data was deleted.")
                return 1

        print("\nDeleting...")
        total_deleted_scan_logs = 0
        total_deleted_orders = 0
        total_adjusted_packs = 0
        total_adjusted_qty = 0
        total_missing_event_packs = 0

        for order in orders.values():
            ticket_ids = [t.id for t in order.tickets or []]

            try:
                # 1. Delete scan logs linked to tickets
                deleted_scan_logs = delete_scan_logs(db, ticket_ids)

                # 2. Optionally adjust sold_count (completed orders only)
                adjust_summary = {"packs_updated": 0, "total_qty": 0, "missing_event_packs": 0}
                if args.adjust_sold_count:
                    adjust_summary = adjust_sold_counts(db, order)

                # 3. Delete the order (cascade deletes items + tickets)
                db.delete(order)

                db.commit()

                total_deleted_scan_logs += deleted_scan_logs
                total_deleted_orders += 1
                total_adjusted_packs += adjust_summary["packs_updated"]
                total_adjusted_qty += adjust_summary["total_qty"]
                total_missing_event_packs += adjust_summary["missing_event_packs"]

                print(
                    f"Deleted order {order.order_number} ({order.id}) "
                    f"scan_logs={deleted_scan_logs}"
                )

            except Exception as e:
                db.rollback()
                print(f"Error deleting order {order.order_number} ({order.id}): {e}")

        print("\nSummary:")
        print(f"  Orders deleted: {total_deleted_orders}")
        print(f"  Scan logs deleted: {total_deleted_scan_logs}")
        if args.adjust_sold_count:
            print(f"  Event packs updated: {total_adjusted_packs}")
            print(f"  Total qty decremented: {total_adjusted_qty}")
            if total_missing_event_packs:
                print(f"  Missing event_packs: {total_missing_event_packs}")

        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
