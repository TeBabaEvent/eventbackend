"""Client PayPal pour le système de billetterie BABA Event.

Documentation: https://developer.paypal.com/docs/api/orders/v2/

Utilise httpx directement pour une compatibilité maximale.
"""

import httpx
import base64
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

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
        
        # Base URL selon l'environnement
        if self.is_sandbox:
            self.base_url = "https://api-m.sandbox.paypal.com"
        else:
            self.base_url = "https://api-m.paypal.com"

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
        self._access_token = None
        self._token_expires_at = None

    def _get_auth_header(self) -> str:
        """Génère le header d'authentification Basic pour obtenir le token."""
        credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _get_access_token(self) -> str:
        """Obtient un access token OAuth2 (avec cache)."""
        # Vérifier si le token est encore valide
        if self._access_token and self._token_expires_at:
            if datetime.now(timezone.utc) < self._token_expires_at:
                return self._access_token

        # Obtenir un nouveau token
        url = f"{self.config.base_url}/v1/oauth2/token"
        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = "grant_type=client_credentials"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, content=data)
                response.raise_for_status()
                result = response.json()

            self._access_token = result["access_token"]
            expires_in = result.get("expires_in", 3600)
            # Expire 5 minutes avant pour éviter les problèmes
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)
            
            logger.info("✅ PayPal access token obtenu")
            return self._access_token

        except Exception as e:
            logger.error(f"Erreur obtention token PayPal: {e}")
            raise

    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: dict = None,
        idempotency_key: str = None
    ) -> Dict[str, Any]:
        """Effectue une requête authentifiée à l'API PayPal."""
        url = f"{self.config.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        # Ajouter PayPal-Request-Id pour l'idempotence si fourni
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key

        try:
            with httpx.Client(timeout=30.0) as client:
                if method == "GET":
                    response = client.get(url, headers=headers)
                elif method == "POST":
                    if json_data:
                        response = client.post(url, headers=headers, json=json_data)
                    else:
                        # Pour les POST sans body (comme capture)
                        response = client.post(url, headers=headers)
                else:
                    raise ValueError(f"Méthode HTTP non supportée: {method}")
                
                response.raise_for_status()
                
                # Certaines réponses peuvent être vides
                if response.text:
                    return response.json()
                return {}

        except httpx.HTTPStatusError as e:
            logger.error(f"Erreur HTTP PayPal: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Erreur requête PayPal: {e}")
            raise

    def create_order(
        self,
        amount: float,
        description: str,
        return_url: str,
        cancel_url: str,
        reference_id: str,
        custom_id: Optional[str] = None,
        locale: str = "fr-BE",
        payer_email: Optional[str] = None,
        payer_name: Optional[str] = None,
        payer_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Crée une commande PayPal (mode redirect).

        Args:
            amount: Montant en EUR (ex: 25.00)
            description: Description affichée au client
            return_url: URL retour après paiement réussi
            cancel_url: URL retour si annulé
            reference_id: Référence interne (order_number)
            custom_id: ID custom optionnel
            locale: Langue de la page de paiement
            payer_email: Email du client (pour pré-remplir sur PayPal)
            payer_name: Nom complet du client (pour pré-remplir sur PayPal)
            payer_phone: Téléphone du client (pour pré-remplir sur PayPal)

        Returns:
            dict: {
                "id": "PAYPAL_ORDER_ID",
                "approve_url": "https://www.paypal.com/checkoutnow?token=...",
                "status": "CREATED"
            }
        """
        # PayPal attend le montant en string avec 2 décimales
        amount_str = f"{amount:.2f}"

        # Construction du payload
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": reference_id,
                "description": description[:127],  # Max 127 chars
                "custom_id": custom_id or reference_id,
                "amount": {
                    "currency_code": "EUR",
                    "value": amount_str
                }
            }]
        }

        # Pré-remplir les informations du payeur si fournies
        # Cela permet de pré-remplir les champs sur la page PayPal (Bancontact, carte, etc.)
        if payer_email or payer_name or payer_phone:
            payer_data = {}
            if payer_email:
                payer_data["email_address"] = payer_email
            if payer_name:
                # Séparer le nom en prénom/nom
                name_parts = payer_name.strip().split(" ", 1)
                payer_data["name"] = {
                    "given_name": name_parts[0],
                    "surname": name_parts[1] if len(name_parts) > 1 else name_parts[0]
                }
            if payer_phone:
                # Nettoyer le numéro de téléphone (garder uniquement chiffres et +)
                clean_phone = ''.join(c for c in payer_phone if c.isdigit() or c == '+')
                if clean_phone:
                    payer_data["phone"] = {
                        "phone_type": "MOBILE",
                        "phone_number": {
                            "national_number": clean_phone.lstrip('+')
                        }
                    }
            order_data["payer"] = payer_data

        # Mode redirect : on utilise application_context pour les URLs de retour
        order_data["application_context"] = {
            "brand_name": "BABA Events",
            "locale": locale,
            "landing_page": "NO_PREFERENCE",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
            "shipping_preference": "NO_SHIPPING"
        }

        logger.info(f"Création commande PayPal: {amount_str} EUR - {description[:50]}")

        try:
            result = self._make_request(
                "POST", 
                "/v2/checkout/orders", 
                order_data,
                idempotency_key=f"create-{reference_id}"
            )
            
            # Trouver l'URL d'approbation
            approve_url = None
            for link in result.get("links", []):
                rel = link.get("rel")
                if rel == "payer-action" or rel == "approve":
                    approve_url = link.get("href")
                    # On privilégie payer-action si présent (mais peu probable si on a les deux sans payment_source)
                    if rel == "payer-action":
                        break
            
            logger.info(f"Commande PayPal créée: {result.get('id')} - Status: {result.get('status')}")

            return {
                "id": result.get("id"),
                "approve_url": approve_url,
                "status": result.get("status"),
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
            dict: Détails de la capture avec capture_id
        """
        try:
            result = self._make_request(
                "POST", 
                f"/v2/checkout/orders/{order_id}/capture",
                idempotency_key=f"capture-{order_id}"
            )
            
            logger.info(f"Commande PayPal capturée: {order_id} - Status: {result.get('status')}")
            
            # Extraire le capture_id pour les remboursements ultérieurs
            capture_id = None
            purchase_units = result.get("purchase_units", [])
            if purchase_units:
                payments = purchase_units[0].get("payments", {})
                captures = payments.get("captures", [])
                if captures:
                    capture_id = captures[0].get("id")
            
            return {
                "id": result.get("id"),
                "status": result.get("status"),
                "capture_id": capture_id,
                "purchase_units": purchase_units
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
            result = self._make_request("GET", f"/v2/checkout/orders/{order_id}")
            
            status = result.get("status")
            
            return {
                "id": result.get("id"),
                "status": status,
                "is_completed": status == "COMPLETED",
                "is_approved": status == "APPROVED",
                "is_created": status == "CREATED",
                "purchase_units": result.get("purchase_units", []),
                "payer": result.get("payer"),
                "create_time": result.get("create_time"),
                "update_time": result.get("update_time")
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
            refund_data = {}
            
            if amount:
                refund_data["amount"] = {
                    "value": f"{amount:.2f}",
                    "currency_code": "EUR"
                }
            
            if note:
                refund_data["note_to_payer"] = note

            result = self._make_request(
                "POST", 
                f"/v2/payments/captures/{capture_id}/refund", 
                refund_data if refund_data else {}
            )
            
            logger.info(f"Remboursement PayPal créé: {result.get('id')}")
            
            return {
                "id": result.get("id"),
                "status": result.get("status"),
                "amount": result.get("amount")
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
    raw_body: bytes,
    paypal_client_instance: PayPalPaymentClient = None
) -> bool:
    """
    Vérifie la signature d'un webhook PayPal via l'API PayPal.
    
    Args:
        webhook_id: ID du webhook configuré dans PayPal
        transmission_id: Header PAYPAL-TRANSMISSION-ID
        timestamp: Header PAYPAL-TRANSMISSION-TIME
        webhook_signature: Header PAYPAL-TRANSMISSION-SIG
        cert_url: Header PAYPAL-CERT-URL
        auth_algo: Header PAYPAL-AUTH-ALGO
        raw_body: Corps brut de la requête
        paypal_client_instance: Instance du client PayPal (optionnel)
    
    Returns:
        bool: True si signature valide
    """
    import json
    from app.core.config import settings
    
    # Si pas de webhook_id configuré
    if not webhook_id:
        if settings.is_production:
            logger.error("❌ PAYPAL_WEBHOOK_ID non configuré en production - requête rejetée")
            return False
        logger.warning("⚠️ PAYPAL_WEBHOOK_ID non configuré - signature non vérifiée (dev only)")
        return True
    
    # Utiliser l'instance globale si non fournie
    client = paypal_client_instance or paypal_client
    if not client:
        if settings.is_production:
            logger.error("❌ PayPal client non disponible en production - requête rejetée")
            return False
        logger.warning("⚠️ PayPal client non disponible - signature non vérifiée (dev only)")
        return True
    
    # Vérifier que les headers requis sont présents
    if not all([transmission_id, timestamp, webhook_signature, cert_url, auth_algo]):
        logger.warning("❌ Headers PayPal manquants pour la vérification de signature")
        return False
    
    try:
        # Décoder le body JSON
        webhook_event = json.loads(raw_body.decode('utf-8'))
        
        # Appeler l'API de vérification PayPal
        verify_data = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": webhook_signature,
            "transmission_time": timestamp,
            "webhook_id": webhook_id,
            "webhook_event": webhook_event
        }
        
        result = client._make_request(
            "POST", 
            "/v1/notifications/verify-webhook-signature", 
            verify_data
        )
        
        verification_status = result.get("verification_status")
        
        if verification_status == "SUCCESS":
            logger.info("✅ Signature webhook PayPal vérifiée")
            return True
        else:
            logger.warning(f"❌ Signature webhook PayPal invalide: {verification_status}")
            return False
            
    except Exception as e:
        logger.error(f"Erreur vérification signature webhook: {e}")
        # En production, rejeter en cas d'erreur de vérification
        # PayPal renverra le webhook plus tard
        if settings.is_production:
            logger.error("❌ Erreur de vérification en production - requête rejetée (PayPal réessayera)")
            return False
        # En dev, accepter pour faciliter le développement
        logger.warning("⚠️ Erreur de vérification acceptée en dev uniquement")
        return True


# ============================================
# SINGLETON - Utiliser cette instance
# ============================================

paypal_config = None
paypal_client = None

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
        logger.warning("⚠️ PayPal client non initialisé: credentials manquants")
except Exception as e:
    logger.warning(f"⚠️ PayPal client non initialisé: {e}")
