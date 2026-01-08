"""Client PayPal pour le système de billetterie BABA Event.

Remplace le client Mollie.
Documentation: https://developer.paypal.com/docs/api/orders/v2/
SDK: https://github.com/paypal/PayPal-Python-Server-SDK
"""

from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.logging.configuration.api_logging_configuration import (
    LoggingConfiguration,
    RequestLoggingConfiguration,
    ResponseLoggingConfiguration,
)
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.controllers.orders_controller import OrdersController
from paypalserversdk.controllers.payments_controller import PaymentsController
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.pay_pal_wallet import PayPalWallet
from paypalserversdk.models.pay_pal_wallet_experience_context import PayPalWalletExperienceContext

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PayPalConfig:
    """Configuration PayPal."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        mode: str = "sandbox"
    ):
        from app.core.config import settings
        self.client_id = client_id or settings.paypal_client_id
        self.client_secret = client_secret or settings.paypal_client_secret
        self.mode = mode or settings.paypal_mode
        
        if not self.client_id or not self.client_secret:
            raise ValueError("PAYPAL_CLIENT_ID et PAYPAL_CLIENT_SECRET doivent être configurés")
        
        self.is_sandbox = self.mode == "sandbox"
        self.is_live = self.mode == "live"

    def __repr__(self):
        return f"<PayPalConfig(mode={self.mode})>"


class PayPalPaymentClient:
    """
    Client pour interagir avec l'API PayPal Orders/Payments.

    Usage:
        from app.services.paypal_client import paypal_client

        # Créer une commande PayPal
        order = paypal_client.create_order(
            amount=25.00,
            description="Billets Concert x2",
            return_url="https://...",
            cancel_url="https://...",
            reference_id="BABA-ABC123"
        )

        # Rediriger vers order["approve_url"]
    """

    def __init__(self, config: PayPalConfig = None):
        self.config = config or PayPalConfig()
        
        # Initialiser le client PayPal SDK
        self.client = PaypalServersdkClient(
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=self.config.client_id,
                o_auth_client_secret=self.config.client_secret,
            ),
            environment=self.config.mode,
            logging_configuration=LoggingConfiguration(
                log_level=logging.INFO,
                mask_sensitive_headers=True,
                request_logging_config=RequestLoggingConfiguration(
                    log_body=True
                ),
                response_logging_config=ResponseLoggingConfiguration(
                    log_body=True
                )
            )
        )
        
        self.orders_controller: OrdersController = self.client.orders
        self.payments_controller: PaymentsController = self.client.payments

    def create_order(
        self,
        amount: float,
        description: str,
        return_url: str,
        cancel_url: str,
        reference_id: str,
        custom_id: Optional[str] = None,
        locale: str = "fr-BE"
    ) -> Dict[str, Any]:
        """
        Crée une commande PayPal.

        Args:
            amount: Montant en EUR (ex: 25.00)
            description: Description affichée au client
            return_url: URL retour après paiement réussi
            cancel_url: URL retour si annulé
            reference_id: Référence interne (order_number)
            custom_id: ID custom optionnel
            locale: Langue de la page de paiement

        Returns:
            dict: {
                "id": "PAYPAL_ORDER_ID",
                "approve_url": "https://www.paypal.com/checkoutnow?token=...",
                "status": "CREATED"
            }
        """
        # PayPal attend le montant en string avec 2 décimales
        amount_str = f"{amount:.2f}"

        order_request = OrderRequest(
            intent=CheckoutPaymentIntent.CAPTURE,
            purchase_units=[
                PurchaseUnitRequest(
                    reference_id=reference_id,
                    description=description,
                    custom_id=custom_id or reference_id,
                    amount=AmountWithBreakdown(
                        currency_code="EUR",
                        value=amount_str
                    )
                )
            ],
            payment_source=PaymentSource(
                paypal=PayPalWallet(
                    experience_context=PayPalWalletExperienceContext(
                        payment_method_preference="IMMEDIATE_PAYMENT_REQUIRED",
                        brand_name="BABA Events",
                        locale=locale,
                        landing_page="LOGIN",
                        user_action="PAY_NOW",
                        return_url=return_url,
                        cancel_url=cancel_url
                    )
                )
            )
        )

        logger.info(f"Création commande PayPal: {amount_str} EUR - {description}")

        try:
            response = self.orders_controller.orders_create({"body": order_request})
            order = response.body
            
            # Trouver l'URL d'approbation
            approve_url = None
            for link in order.get("links", []):
                if link.get("rel") == "payer-action":
                    approve_url = link.get("href")
                    break
            
            logger.info(f"Commande PayPal créée: {order.get('id')} - Status: {order.get('status')}")

            return {
                "id": order.get("id"),
                "approve_url": approve_url,
                "status": order.get("status"),
                "reference_id": reference_id
            }

        except Exception as e:
            logger.error(f"Erreur création commande PayPal: {e}")
            raise

    def capture_order(self, order_id: str) -> Dict[str, Any]:
        """
        Capture (finalise) une commande PayPal après approbation.

        Args:
            order_id: ID de la commande PayPal

        Returns:
            dict: Détails de la capture
        """
        try:
            response = self.orders_controller.orders_capture({
                "id": order_id,
                "prefer": "return=representation"
            })
            capture = response.body
            
            logger.info(f"Commande PayPal capturée: {order_id} - Status: {capture.get('status')}")
            
            return {
                "id": capture.get("id"),
                "status": capture.get("status"),
                "purchase_units": capture.get("purchase_units", [])
            }

        except Exception as e:
            logger.error(f"Erreur capture commande PayPal {order_id}: {e}")
            raise

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Récupère les détails d'une commande PayPal.

        Args:
            order_id: ID de la commande PayPal

        Returns:
            dict: Détails de la commande
        """
        try:
            response = self.orders_controller.orders_get({"id": order_id})
            order = response.body
            
            status = order.get("status")
            purchase_units = order.get("purchase_units", [])
            
            return {
                "id": order.get("id"),
                "status": status,
                "is_completed": status == "COMPLETED",
                "is_approved": status == "APPROVED",
                "is_created": status == "CREATED",
                "purchase_units": purchase_units,
                "payer": order.get("payer"),
                "create_time": order.get("create_time"),
                "update_time": order.get("update_time")
            }

        except Exception as e:
            logger.error(f"Erreur récupération commande PayPal {order_id}: {e}")
            raise

    def create_refund(
        self,
        capture_id: str,
        amount: float = None,
        note: str = None
    ) -> Dict[str, Any]:
        """
        Rembourse un paiement PayPal (total ou partiel).

        Args:
            capture_id: ID de la capture PayPal
            amount: Montant à rembourser en EUR (None = total)
            note: Note du remboursement

        Returns:
            dict: Détails du remboursement
        """
        try:
            refund_request = {}
            
            if amount:
                refund_request["amount"] = {
                    "value": f"{amount:.2f}",
                    "currency_code": "EUR"
                }
            
            if note:
                refund_request["note_to_payer"] = note

            response = self.payments_controller.captures_refund({
                "capture_id": capture_id,
                "body": refund_request if refund_request else None
            })
            refund = response.body
            
            logger.info(f"Remboursement PayPal créé: {refund.get('id')}")
            
            return {
                "id": refund.get("id"),
                "status": refund.get("status"),
                "amount": refund.get("amount")
            }

        except Exception as e:
            logger.error(f"Erreur remboursement PayPal {capture_id}: {e}")
            raise


# ============================================
# VÉRIFICATION WEBHOOK
# ============================================

def verify_webhook_signature(
    webhook_id: str,
    transmission_id: str,
    timestamp: str,
    webhook_signature: str,
    cert_url: str,
    auth_algo: str,
    raw_body: bytes
) -> bool:
    """
    Vérifie la signature d'un webhook PayPal.
    
    Note: PayPal utilise une signature cryptographique pour valider les webhooks.
    Cette fonction doit être appelée avant de traiter tout webhook.
    
    Args:
        webhook_id: ID du webhook configuré dans PayPal
        transmission_id: Header PAYPAL-TRANSMISSION-ID
        timestamp: Header PAYPAL-TRANSMISSION-TIME
        webhook_signature: Header PAYPAL-TRANSMISSION-SIG
        cert_url: Header PAYPAL-CERT-URL
        auth_algo: Header PAYPAL-AUTH-ALGO
        raw_body: Corps brut de la requête
    
    Returns:
        bool: True si signature valide
    """
    # Pour l'instant, on fait confiance au webhook (comme Mollie)
    # TODO: Implémenter la vérification complète avec certificat PayPal
    logger.warning("⚠️ Webhook signature verification not fully implemented - trusting webhook")
    return True


# ============================================
# SINGLETON - Utiliser cette instance
# ============================================

try:
    from app.core.config import settings
    if settings.paypal_client_id and settings.paypal_client_secret:
        paypal_config = PayPalConfig(
            settings.paypal_client_id,
            settings.paypal_client_secret,
            settings.paypal_mode
        )
        paypal_client = PayPalPaymentClient(paypal_config)
        logger.info(f"✅ PayPal client initialisé: {paypal_config}")
    else:
        paypal_config = None
        paypal_client = None
        logger.warning("⚠️ PayPal client non initialisé: credentials manquants")
except Exception as e:
    paypal_config = None
    paypal_client = None
    logger.warning(f"⚠️ PayPal client non initialisé: {e}")

