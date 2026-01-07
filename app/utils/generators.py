"""Générateurs de codes uniques pour les commandes et billets"""
import secrets
import string


def generate_order_number() -> str:
    """
    Génère un numéro de commande unique au format BABA-XXXXXX.

    Format: BABA- suivi de 6 caractères alphanumériques majuscules.
    Utilise secrets.choice pour la sécurité cryptographique.

    Returns:
        str: Numéro de commande (ex: BABA-A1B2C3)

    Example:
        >>> order_num = generate_order_number()
        >>> order_num.startswith("BABA-")
        True
        >>> len(order_num)
        11
    """
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(6))
    return f"BABA-{suffix}"


def generate_ticket_code() -> str:
    """
    Génère un code ticket unique au format BABA-XXXXXXXX.

    Format: BABA- suivi de 8 caractères alphanumériques majuscules.
    Utilise secrets.choice pour la sécurité cryptographique.

    Returns:
        str: Code ticket (ex: BABA-A1B2C3D4)

    Example:
        >>> ticket_code = generate_ticket_code()
        >>> ticket_code.startswith("BABA-")
        True
        >>> len(ticket_code)
        13
    """
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(8))
    return f"BABA-{suffix}"
