"""Client Mollie pour le système de billetterie BABA Event.

Remplace l'ancien client CCV.
Documentation: https://docs.mollie.com/
SDK: https://github.com/mollie/mollie-api-python
"""

from mollie.api.client import Client
from mollie.api.error import Error as MollieError
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class MollieConfig:
    """Configuration Mollie."""

    def __init__(self, api_key: Optional[str] = None):
        from app.core.config import settings
        self.api_key = api_key or settings.mollie_api_key
        if not self.api_key:
            raise ValueError("MOLLIE_API_KEY not configured in .env")

        # Le préfixe de la clé détermine le mode
        self.is_test = self.api_key.startswith("test_")
        self.is_live = self.api_key.startswith("live_")

        if not self.is_test and not self.is_live:
            raise ValueError("MOLLIE_API_KEY must start with 'test_' or 'live_'")

    def __repr__(self):
        mode = "TEST" if self.is_test else "LIVE"
        return f"<MollieConfig(mode={mode})>"


class MolliePaymentClient:
    """
    Client pour interagir avec l'API Mollie Payments.

    Usage:
        from app.services.mollie_client import mollie_client

        # Créer un paiement
        payment = await mollie_client.create_payment(
            amount=25.00,
            description="Billets Concert x2",
            redirect_url="https://...",
            webhook_url="https://...",
            metadata={"order_number": "BABA-ABC123"}
        )

        # Rediriger vers payment["checkout_url"]
    """

    def __init__(self, config: MollieConfig = None):
        self.config = config or MollieConfig()
        self.client = Client()
        self.client.set_api_key(self.config.api_key)

    def create_payment(
        self,
        amount: float,
        description: str,
        redirect_url: str,
        webhook_url: str,
        metadata: Dict[str, Any] = None,
        method: str = None,
        locale: str = "fr_BE"
    ) -> Dict[str, Any]:
        """
        Crée un paiement Mollie.

        Args:
            amount: Montant en EUR (ex: 25.00)
            description: Description affichée au client
            redirect_url: URL retour après paiement
            webhook_url: URL webhook pour notifications
            metadata: Données custom (ex: {"order_number": "BABA-123"})
            method: Méthode de paiement spécifique (optionnel)
                    - "bancontact" : Bancontact uniquement
                    - "creditcard" : Carte de crédit
                    - "ideal" : iDEAL (Pays-Bas)
                    - None : Laisser le client choisir
            locale: Langue de la page de paiement
                    - "fr_BE" : Français (Belgique)
                    - "nl_BE" : Néerlandais (Belgique)
                    - "en_US" : Anglais

        Returns:
            dict: {
                "id": "tr_xxx",
                "checkout_url": "https://...",
                "status": "open",
                "metadata": {...}
            }

        Raises:
            MollieError: En cas d'erreur API
        """
        # Mollie attend le montant en string avec 2 décimales
        amount_str = f"{amount:.2f}"

        payment_data = {
            "amount": {
                "currency": "EUR",
                "value": amount_str
            },
            "description": description,
            "redirectUrl": redirect_url,
            "webhookUrl": webhook_url,
            "locale": locale
        }

        # Méthode spécifique (optionnel)
        if method:
            payment_data["method"] = method

        # Metadata pour stocker des informations custom
        if metadata:
            payment_data["metadata"] = metadata

        logger.info(f"Création paiement Mollie: {amount_str} EUR - {description}")

        try:
            payment = self.client.payments.create(payment_data)

            logger.info(f"Paiement Mollie créé: {payment.id} - Status: {payment.status}")

            return {
                "id": payment.id,
                "checkout_url": payment.checkout_url,
                "status": payment.status,
                "metadata": dict(payment.metadata) if payment.metadata else None,
                "method": payment.method,
                "created_at": payment.created_at
            }

        except MollieError as e:
            logger.error(f"Erreur création paiement Mollie: {e}")
            raise

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        """
        Récupère les détails d'un paiement.

        IMPORTANT: Toujours appeler cette méthode après un webhook
        car les webhooks Mollie ne contiennent que l'ID, pas les données.

        Args:
            payment_id: ID du paiement Mollie (ex: "tr_xxx")

        Returns:
            dict: {
                "id": "tr_xxx",
                "status": "paid",
                "is_paid": True,
                "is_pending": False,
                ...
            }
        """
        try:
            payment = self.client.payments.get(payment_id)

            return {
                "id": payment.id,
                "status": payment.status,
                "is_paid": payment.is_paid(),
                "is_pending": payment.is_pending(),
                "is_open": payment.is_open(),
                "is_failed": payment.is_failed(),
                "is_canceled": payment.is_canceled(),
                "is_expired": payment.is_expired(),
                "amount": {
                    "currency": payment.amount["currency"],
                    "value": payment.amount["value"]
                },
                "metadata": dict(payment.metadata) if payment.metadata else None,
                "method": payment.method,
                "paid_at": getattr(payment, 'paid_at', None),
                "canceled_at": getattr(payment, 'canceled_at', None),
                "expired_at": getattr(payment, 'expired_at', None),
                "failed_at": getattr(payment, 'failed_at', None),
                "description": payment.description
            }

        except MollieError as e:
            logger.error(f"Erreur récupération paiement Mollie {payment_id}: {e}")
            raise

    def create_refund(
        self,
        payment_id: str,
        amount: float = None,
        description: str = None
    ) -> Dict[str, Any]:
        """
        Rembourse un paiement (total ou partiel).

        Note: Les remboursements partiels sont supportés.
        On peut faire plusieurs remboursements jusqu'au montant total.

        Args:
            payment_id: ID du paiement Mollie (ex: "tr_xxx")
            amount: Montant à rembourser en EUR (None = total)
            description: Raison du remboursement

        Returns:
            dict: {
                "id": "re_xxx",
                "status": "pending",
                "amount": {...}
            }
        """
        try:
            payment = self.client.payments.get(payment_id)

            refund_data = {}

            # Montant partiel
            if amount:
                refund_data["amount"] = {
                    "currency": "EUR",
                    "value": f"{amount:.2f}"
                }

            # Description
            if description:
                refund_data["description"] = description

            logger.info(f"Création remboursement pour {payment_id}: {amount or 'total'} EUR")

            refund = payment.refunds.create(refund_data)

            logger.info(f"Remboursement créé: {refund.id} - Status: {refund.status}")

            return {
                "id": refund.id,
                "status": refund.status,
                "amount": {
                    "currency": refund.amount["currency"],
                    "value": refund.amount["value"]
                },
                "payment_id": payment_id
            }

        except MollieError as e:
            logger.error(f"Erreur remboursement Mollie {payment_id}: {e}")
            raise

    def list_payment_methods(self, locale: str = "fr_BE") -> list:
        """
        Liste les méthodes de paiement actives.

        Utile pour afficher les options disponibles côté frontend.

        Args:
            locale: Langue pour les descriptions

        Returns:
            list: [{"id": "bancontact", "description": "Bancontact"}, ...]
        """
        try:
            methods = self.client.methods.list(locale=locale)

            return [
                {
                    "id": method.id,
                    "description": method.description,
                    "image": {
                        "size1x": method.image["size1x"],
                        "size2x": method.image["size2x"],
                        "svg": method.image["svg"]
                    },
                    "minimum_amount": method.minimum_amount,
                    "maximum_amount": method.maximum_amount
                }
                for method in methods
            ]

        except MollieError as e:
            logger.error(f"Erreur liste méthodes Mollie: {e}")
            raise


# ============================================
# SINGLETON - Utiliser cette instance
# ============================================

try:
    from app.core.config import settings
    mollie_config = MollieConfig(settings.mollie_api_key)
    mollie_client = MolliePaymentClient(mollie_config)
    logger.info(f"✅ Mollie client initialisé: {mollie_config}")
except ValueError as e:
    # En dev sans clé configurée
    mollie_config = None
    mollie_client = None
    logger.warning(f"⚠️  Mollie client non initialisé: {e}")
