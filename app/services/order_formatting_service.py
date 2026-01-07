"""Service de formatage des informations d'affichage des commandes"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import Order, Pack

logger = logging.getLogger(__name__)


def _format_pack_with_quantity(pack_name: str, quantity: int) -> str:
    """
    Formater le nom du pack avec la quantité si nécessaire.

    Args:
        pack_name: Nom du pack
        quantity: Quantité

    Returns:
        Nom formaté avec quantité ("VIP x2") ou nom seul si quantity <= 1
    """
    return f"{pack_name} x{quantity}" if quantity > 1 else pack_name


def format_pack_display(order: "Order", separator: str = ", ", locale: str = "fr") -> str:
    """
    Format pack names for display with quantities.

    Args:
        order: Order instance (multi-pack or legacy)
        separator: String to join multiple packs (default: ", ")
        locale: Language code for translations (default: "fr")

    Returns:
        Formatted string like "VIP x2, Standard x3" or "VIP"

    Examples:
        >>> format_pack_display(multi_pack_order)
        "VIP x2, Standard x3"

        >>> format_pack_display(single_pack_order)
        "VIP"

        >>> format_pack_display(legacy_order)
        "Premium"
    """
    try:
        if order.is_cart_order:
            # Multi-pack order: format each item
            if not order.items:
                return "N/A"

            parts = [
                _format_pack_with_quantity(_get_translated_pack_name(item.pack, locale), item.quantity)
                for item in order.items
            ]

            result = separator.join(parts)
            logger.debug(f"Formatted multi-pack display: {result}")
            return result

        else:
            # Legacy single-pack order
            if order.pack:
                pack_name = _get_translated_pack_name(order.pack, locale)
                result = _format_pack_with_quantity(pack_name, order.quantity or 0)

                logger.debug(f"Formatted legacy pack display: {result}")
                return result

            return "N/A"
    except Exception as e:
        logger.error(f"Error formatting pack display for order {order.id}: {e}")
        return "Error"


def _get_translated_pack_name(pack: "Pack", locale: str = "fr") -> str:
    """
    Get pack name with translation support.

    Args:
        pack: Pack model instance
        locale: Language code

    Returns:
        Translated pack name or fallback to default name
    """
    if not pack:
        return "Unknown"

    # Try to get translated name
    if hasattr(pack, 'name_translations') and pack.name_translations and locale in pack.name_translations:
        translated = pack.name_translations.get(locale)
        if translated:
            return translated

    # Fallback to default name
    return pack.name


def format_pack_display_short(order: "Order", max_length: int = 30) -> str:
    """
    Format pack display with length limit for compact views.

    Args:
        order: Order instance
        max_length: Maximum string length before truncation

    Returns:
        Truncated string with "..." if too long

    Examples:
        >>> format_pack_display_short(long_order, max_length=20)
        "VIP x2, Standard..."
    """
    full_display = format_pack_display(order)

    if len(full_display) > max_length:
        return full_display[:max_length - 3] + "..."

    return full_display


def get_pack_items_for_display(order: "Order") -> list[dict]:
    """
    Get structured pack items for detailed displays.

    Args:
        order: Order instance

    Returns:
        List of dicts with pack details and quantities

    Example:
        >>> get_pack_items_for_display(order)
        [
            {
                "pack_id": "123",
                "pack_name": "VIP",
                "pack_type": "vip",
                "quantity": 2,
                "unit_price": 50.0,
                "subtotal": 100.0
            }
        ]
    """
    items = []

    try:
        if order.is_cart_order:
            for order_item in order.items:
                pack = order_item.pack
                items.append({
                    "pack_id": order_item.pack_id,
                    "pack_name": getattr(pack, 'name', 'Unknown'),
                    "pack_type": getattr(pack, 'type', None) if pack else None,
                    "quantity": order_item.quantity,
                    "unit_price": order_item.unit_price,
                    "subtotal": order_item.unit_price * order_item.quantity
                })
        else:
            # Legacy order
            if order.pack:
                pack_price = getattr(order.pack, 'price', 0.0)
                items.append({
                    "pack_id": order.pack_id,
                    "pack_name": order.pack.name,
                    "pack_type": getattr(order.pack, 'type', None),
                    "quantity": order.quantity or 0,
                    "unit_price": pack_price,
                    "subtotal": pack_price * (order.quantity or 0)
                })
    except Exception as e:
        logger.error(f"Error getting pack items for order {order.id}: {e}")

    return items
