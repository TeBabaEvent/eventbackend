"""Service d'envoi d'emails via Gmail SMTP"""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import List, Optional, Tuple
import logging

from app.db.models import Order, Ticket
from app.core.config import settings

logger = logging.getLogger(__name__)

# Chemins
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates', 'email')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')


class EmailService:
    """Service pour l'envoi d'emails transactionnels"""

    def __init__(self):
        """Initialise le service email avec la configuration Gmail"""
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.email = settings.gmail_address or ""
        self.password = settings.gmail_app_password or ""
        self.from_name = settings.email_from_name

        if not self.email or not self.password:
            logger.warning("Gmail SMTP non configuré dans .env")

        # Configurer Jinja2 pour les templates
        try:
            self.jinja_env = Environment(
                loader=FileSystemLoader(TEMPLATE_DIR),
                autoescape=select_autoescape(['html'])
            )
        except Exception as e:
            logger.warning(f"Templates email non trouvés: {e}")
            self.jinja_env = None
    
    def _get_logo(self) -> Optional[Tuple[bytes, str, str]]:
        """
        Récupère le logo pour l'email.
        
        Returns:
            Tuple[bytes, str, str]: (contenu, content_type, extension) ou None
        """
        logo_paths = [
            ('logo.png', 'image/png'),
            ('logo.jpg', 'image/jpeg'),
            ('logo.jpeg', 'image/jpeg'),
        ]
        
        for filename, content_type in logo_paths:
            path = os.path.join(STATIC_DIR, 'images', filename)
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        return (f.read(), content_type, filename.split('.')[-1])
                except Exception as e:
                    logger.warning(f"Erreur lecture logo {filename}: {e}")
        
        return None

    def _create_message(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        attachments: Optional[List[tuple]] = None,
        embedded_images: Optional[List[Tuple[bytes, str, str]]] = None
    ) -> MIMEMultipart:
        """
        Crée un message email MIME.

        Args:
            to_email: Adresse email destinataire
            subject: Sujet de l'email
            html_content: Contenu HTML de l'email
            attachments: Liste de tuples (filepath, filename)
            embedded_images: Liste de tuples (bytes, content_id, content_type)

        Returns:
            MIMEMultipart: Message prêt à envoyer
        """
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{self.from_name} <{self.email}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Partie alternative (pour le HTML avec images embarquées)
        msg_related = MIMEMultipart("related")
        
        # Corps HTML
        html_part = MIMEText(html_content, "html", "utf-8")
        msg_related.attach(html_part)
        
        # Images embarquées (CID)
        if embedded_images:
            for img_data, content_id, content_type in embedded_images:
                try:
                    img_part = MIMEImage(img_data)
                    img_part.add_header("Content-ID", f"<{content_id}>")
                    img_part.add_header("Content-Disposition", "inline", filename=content_id)
                    msg_related.attach(img_part)
                except Exception as e:
                    logger.warning(f"Erreur ajout image embarquée {content_id}: {e}")
        
        msg.attach(msg_related)

        # Pièces jointes
        if attachments:
            for filepath, filename in attachments:
                try:
                    with open(filepath, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            "Content-Disposition",
                            f"attachment; filename={filename}"
                        )
                        msg.attach(part)
                except Exception as e:
                    logger.error(f"Erreur ajout pièce jointe {filename}: {e}")

        return msg

    def _send(self, msg: MIMEMultipart):
        """
        Envoie un message via SMTP Gmail.

        Args:
            msg: Message MIME à envoyer

        Raises:
            Exception: Si l'envoi échoue
        """
        if not self.email or not self.password:
            raise ValueError("Gmail SMTP non configuré")

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email, self.password)
                server.send_message(msg)

            logger.info(f"Email envoyé à {msg['To']}")

        except smtplib.SMTPAuthenticationError:
            logger.error("Erreur d'authentification Gmail - Vérifiez GMAIL_APP_PASSWORD")
            raise
        except Exception as e:
            logger.error(f"Erreur envoi email: {e}")
            raise

    async def send_confirmation(
        self,
        to_email: str,
        customer_name: str,
        order: Order,
        tickets: List[Ticket],
        pdf_path: str
    ):
        """
        Envoie l'email de confirmation avec les billets.
        Supporte les commandes single-pack (legacy) et multi-pack.

        Args:
            to_email: Email du client
            customer_name: Nom du client
            order: Commande associée
            tickets: Liste des tickets générés
            pdf_path: Chemin vers le PDF des billets

        Raises:
            Exception: Si l'envoi échoue
        """
        logger.info(f"Envoi email confirmation à {to_email}")

        # Utiliser les propriétés helper du modèle Order
        pack_items = order.pack_items_list
        pack_display = order.pack_display
        
        # Récupérer le logo si disponible
        logo_data = self._get_logo()
        logo_cid = "logo" if logo_data else None

        # Préparer les données pour le template
        template_data = {
            "customer_name": customer_name,
            "order_number": order.order_number,
            "event_name": order.event.title,
            "event_date": order.event.date,
            "event_time": order.event.time,
            "event_location": order.event.location,
            "event_city": order.event.city,
            "event_address": order.event.address or "",
            "quantity": order.total_quantity,
            "amount": order.amount / 100,  # Convertir en EUR
            "pack_display": pack_display,
            "pack_items": pack_items,
            "is_multi_pack": len(pack_items) > 1,
            "tickets": tickets,
            "logo_cid": logo_cid,
        }

        # Générer le HTML depuis le template
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template("confirmation.html")
                html = template.render(**template_data)
            except Exception as e:
                logger.error(f"Erreur template confirmation: {e}")
                # Fallback vers HTML simple
                html = self._generate_simple_confirmation_html(template_data)
        else:
            html = self._generate_simple_confirmation_html(template_data)

        # Préparer les images embarquées
        embedded_images = []
        if logo_data:
            img_bytes, content_type, _ = logo_data
            embedded_images.append((img_bytes, "logo", content_type))

        # Créer et envoyer le message
        msg = self._create_message(
            to_email=to_email,
            subject=f"Vos billets pour {order.event.title}",
            html_content=html,
            attachments=[(pdf_path, f"billets-{order.order_number}.pdf")],
            embedded_images=embedded_images if embedded_images else None
        )

        self._send(msg)

    def _generate_simple_confirmation_html(self, data: dict) -> str:
        """
        Génère un HTML simple si le template Jinja2 n'est pas disponible.
        Design dark premium cohérent avec le site.

        Args:
            data: Données de la commande

        Returns:
            str: HTML de l'email
        """
        # Build pack breakdown HTML
        pack_html = ""
        if data.get('is_multi_pack') and data.get('pack_items'):
            pack_html = "".join([
                f'<div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #1a1a1e;"><span style="color: #a0a0a0;">{p["name"]}</span><span style="color: #fff;">x{p["quantity"]}</span></div>'
                for p in data['pack_items']
            ])
        else:
            pack_html = f'<div style="color: #a0a0a0;">{data.get("pack_display", "Standard")}</div>'

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0a0a0f;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; background-color: #0a0a0f;">
        <!-- Header -->
        <tr>
            <td style="padding: 40px 30px 20px; text-align: center;">
                <h1 style="color: #dc143c; margin: 0; font-size: 28px; font-weight: 800; letter-spacing: 2px;">BABA EVENT</h1>
            </td>
        </tr>

        <!-- Main Content -->
        <tr>
            <td style="padding: 20px 30px;">
                <h2 style="color: #ffffff; margin: 0 0 10px; font-size: 24px; font-weight: 700; text-align: center;">
                    Merci {data['customer_name']} !
                </h2>
                <p style="color: #a0a0a0; font-size: 15px; line-height: 1.6; margin: 0 0 30px; text-align: center;">
                    Votre réservation est confirmée. Vos billets sont en pièce jointe.
                </p>

                <!-- Order Card -->
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #141418; border: 1px solid #2a2a2e; border-radius: 16px; overflow: hidden;">
                    <!-- Order Header -->
                    <tr>
                        <td style="padding: 16px 20px; background: #1a1a1e; border-bottom: 1px solid #2a2a2e;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="color: #fff; font-family: 'Courier New', monospace; font-size: 14px; font-weight: 600;">{data['order_number']}</td>
                                    <td style="text-align: right;"><span style="background: #1a3d2e; color: #10b981; padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600; text-transform: uppercase;">Confirmé</span></td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Event Info -->
                    <tr>
                        <td style="padding: 24px 20px;">
                            <h3 style="color: #ffffff; margin: 0 0 16px; font-size: 20px; font-weight: 700;">{data['event_name']}</h3>
                            
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="padding: 8px 0; color: #e0e0e0; font-size: 14px;">{data['event_date']} à {data['event_time']}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; color: #e0e0e0; font-size: 14px;">{data['event_location']}, {data['event_city']}</td>
                                </tr>
                            </table>

                            <!-- Divider -->
                            <div style="height: 1px; background: #2a2a2e; margin: 20px 0;"></div>

                            <!-- Order Details -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="padding: 8px 0; color: #808080; font-size: 13px;">Billets</td>
                                    <td style="padding: 8px 0; color: #fff; font-size: 14px; font-weight: 600; text-align: right;">{data['quantity']}</td>
                                </tr>
                            </table>
                            
                            {pack_html}

                            <!-- Total -->
                            <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #2a2a2e;">
                                <table width="100%" cellpadding="0" cellspacing="0">
                                    <tr>
                                        <td style="color: #808080; font-size: 13px;">Total payé</td>
                                        <td style="color: #dc143c; font-size: 20px; font-weight: 700; text-align: right;">{data['amount']:.2f} €</td>
                                    </tr>
                                </table>
                            </div>
                        </td>
                    </tr>
                </table>

                <!-- Instructions -->
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 24px; background: #0f2920; border: 1px solid #1a4a35; border-radius: 12px;">
                    <tr>
                        <td style="padding: 20px;">
                            <p style="color: #10b981; margin: 0 0 8px; font-size: 14px; font-weight: 600;">Le jour J</p>
                            <p style="color: #a0a0a0; margin: 0; font-size: 13px; line-height: 1.6;">
                                Présentez le QR code de vos billets (PDF en pièce jointe ou sur smartphone) à l'entrée. Chaque billet ne peut être utilisé qu'une seule fois.
                            </p>
                        </td>
                    </tr>
                </table>

                <!-- Contact -->
                <p style="color: #606060; font-size: 13px; margin: 30px 0 0; text-align: center; line-height: 1.6;">
                    Une question ? Contactez-nous sur<br>
                    <a href="mailto:contact@baba.events" style="color: #dc143c; text-decoration: none;">contact@baba.events</a>
                </p>
            </td>
        </tr>

        <!-- Footer -->
        <tr>
            <td style="padding: 30px; text-align: center; border-top: 1px solid #1a1a1e;">
                <p style="color: #404040; font-size: 11px; margin: 0 0 8px; line-height: 1.5;">
                    © 2025 BABA Event - Tous droits réservés
                </p>
                <p style="color: #303030; font-size: 10px; margin: 0; line-height: 1.5;">
                    Cet email concerne votre commande {data['order_number']}
                </p>
            </td>
        </tr>
    </table>
</body>
</html>
        """

    async def send_reminder(
        self,
        to_email: str,
        customer_name: str,
        order: Order,
        pdf_path: str
    ):
        """
        Envoie un email de rappel J-1.

        Args:
            to_email: Email du client
            customer_name: Nom du client
            order: Commande associée
            pdf_path: Chemin vers le PDF des billets
        """
        logger.info(f"Envoi email rappel à {to_email}")

        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0a0a0f;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; background-color: #0a0a0f;">
        <tr>
            <td style="padding: 40px 30px 20px; text-align: center;">
                <h1 style="color: #dc143c; margin: 0; font-size: 28px; font-weight: 800; letter-spacing: 2px;">BABA EVENT</h1>
            </td>
        </tr>
        <tr>
            <td style="padding: 20px 30px;">
                <h2 style="color: #ffffff; margin: 0 0 20px; font-size: 24px; font-weight: 700; text-align: center;">
                    C'est demain !
                </h2>
                <p style="color: #a0a0a0; font-size: 15px; line-height: 1.6; margin: 0 0 30px; text-align: center;">
                    Bonjour {customer_name}, votre événement a lieu demain !
                </p>
                
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #141418; border: 1px solid #2a2a2e; border-radius: 16px; overflow: hidden;">
                    <tr>
                        <td style="padding: 24px 20px;">
                            <h3 style="color: #ffffff; margin: 0 0 16px; font-size: 20px; font-weight: 700;">{order.event.title}</h3>
                            <p style="color: #e0e0e0; font-size: 14px; margin: 8px 0;">{order.event.date} à {order.event.time}</p>
                            <p style="color: #e0e0e0; font-size: 14px; margin: 8px 0;">{order.event.location}, {order.event.city}</p>
                        </td>
                    </tr>
                </table>
                
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 24px; background: #2d2510; border: 1px solid #4a3d1a; border-radius: 12px;">
                    <tr>
                        <td style="padding: 20px;">
                            <p style="color: #fbbf24; margin: 0; font-size: 14px; font-weight: 600;">
                                N'oubliez pas vos billets en pièce jointe !
                            </p>
                        </td>
                    </tr>
                </table>
                
                <p style="color: #a0a0a0; font-size: 15px; margin: 30px 0 0; text-align: center;">À très bientôt !</p>
            </td>
        </tr>
        <tr>
            <td style="padding: 30px; text-align: center; border-top: 1px solid #1a1a1e;">
                <p style="color: #404040; font-size: 11px; margin: 0;">© 2025 BABA Event</p>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        msg = self._create_message(
            to_email=to_email,
            subject=f"Rappel : {order.event.title} demain !",
            html_content=html,
            attachments=[(pdf_path, f"billets-{order.order_number}.pdf")]
        )

        self._send(msg)

    async def send_refund(
        self,
        to_email: str,
        customer_name: str,
        order: Order,
        amount: float
    ):
        """
        Envoie un email de confirmation de remboursement.

        Args:
            to_email: Email du client
            customer_name: Nom du client
            order: Commande remboursée
            amount: Montant remboursé en EUR
        """
        logger.info(f"Envoi email remboursement à {to_email}")

        # Récupérer le logo si disponible
        logo_data = self._get_logo()
        logo_cid = "logo" if logo_data else None
        
        # Générer le header avec ou sans logo
        if logo_cid:
            logo_html = f'<img src="cid:{logo_cid}" alt="BABA Event" style="height: 60px; width: auto; max-width: 200px;">'
        else:
            logo_html = '<h1 style="color: #dc143c; margin: 0; font-size: 32px; font-weight: 800; letter-spacing: 3px; text-transform: uppercase;">BABA EVENT</h1>'

        html = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remboursement confirmé - BABA Event</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #0a0a0f; color: #ffffff;">
    <!-- Wrapper -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #0a0a0f;">
        <tr>
            <td align="center" style="padding: 20px 10px;">
                <!-- Main Container -->
                <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; background-color: #0a0a0f;">
                    
                    <!-- Header / Logo -->
                    <tr>
                        <td style="padding: 40px 30px 20px; text-align: center;">
                            {logo_html}
                        </td>
                    </tr>

                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 20px 30px; text-align: center;">
                            <h2 style="color: #ffffff; margin: 0 0 12px; font-size: 26px; font-weight: 700;">
                                Remboursement confirmé
                            </h2>
                            <p style="color: #909090; font-size: 15px; line-height: 1.6; margin: 0;">
                                Bonjour {customer_name},<br>
                                Votre commande a été remboursée avec succès.
                            </p>
                        </td>
                    </tr>

                    <!-- Refund Card -->
                    <tr>
                        <td style="padding: 10px 30px 30px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: #141418; border: 1px solid #2a2a2e; border-radius: 16px; overflow: hidden;">
                                
                                <!-- Order Header -->
                                <tr>
                                    <td style="padding: 18px 24px; background: #1a1a1e; border-bottom: 1px solid #2a2a2e;">
                                        <table width="100%" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td>
                                                    <span style="color: #ffffff; font-family: 'Courier New', Consolas, monospace; font-size: 14px; font-weight: 700; letter-spacing: 0.5px;">{order.order_number}</span>
                                                </td>
                                                <td style="text-align: right;">
                                                    <span style="background: #3d1a1a; color: #dc143c; padding: 5px 14px; border-radius: 20px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Remboursé</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>

                                <!-- Refund Details -->
                                <tr>
                                    <td style="padding: 28px 24px;">
                                        <!-- Event Title -->
                                        <h3 style="color: #ffffff; margin: 0 0 20px; font-size: 22px; font-weight: 700; line-height: 1.3;">{order.event.title}</h3>
                                        
                                        <!-- Order Details -->
                                        <table width="100%" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="padding: 8px 0; color: #707070; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">Billets annulés</td>
                                                <td style="padding: 8px 0; color: #ffffff; font-size: 15px; font-weight: 600; text-align: right;">{order.quantity}</td>
                                            </tr>
                                        </table>

                                        <!-- Divider -->
                                        <div style="height: 1px; background: #2a2a2e; margin: 24px 0;"></div>

                                        <!-- Refund Amount -->
                                        <table width="100%" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="color: #707070; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">Montant remboursé</td>
                                                <td style="color: #10b981; font-size: 24px; font-weight: 800; text-align: right;">{amount:.2f} €</td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Info Box - Timeline -->
                    <tr>
                        <td style="padding: 0 30px 30px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: #0f2920; border: 1px solid #1a4a35; border-radius: 12px;">
                                <tr>
                                    <td style="padding: 22px 24px;">
                                        <p style="color: #10b981; margin: 0 0 10px; font-size: 15px; font-weight: 700;">
                                            Délai de traitement
                                        </p>
                                        <p style="color: #a0a0a0; margin: 0; font-size: 14px; line-height: 1.7;">
                                            Le remboursement apparaîtra sur votre compte bancaire dans un délai de <strong style="color: #909090;">5 à 10 jours ouvrés</strong>, selon votre établissement bancaire.
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Notice Box -->
                    <tr>
                        <td style="padding: 0 30px 30px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: #2d2510; border: 1px solid #4a3d1a; border-radius: 12px;">
                                <tr>
                                    <td style="padding: 18px 24px;">
                                        <p style="color: #fbbf24; margin: 0; font-size: 13px; line-height: 1.6;">
                                            <strong>Note :</strong> Suite à ce remboursement, vos billets pour cet événement ne sont plus valides et ne pourront pas être utilisés.
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Contact -->
                    <tr>
                        <td style="padding: 0 30px 40px; text-align: center;">
                            <p style="color: #505050; font-size: 14px; margin: 0; line-height: 1.7;">
                                Une question ? Contactez-nous sur<br>
                                <a href="mailto:contact@baba.events" style="color: #dc143c; text-decoration: none; font-weight: 600;">contact@baba.events</a>
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 30px; text-align: center; border-top: 1px solid #1a1a1e;">
                            <p style="color: #404040; font-size: 12px; margin: 0 0 8px; line-height: 1.5;">
                                © 2025 BABA Event - Tous droits réservés
                            </p>
                            <p style="color: #303030; font-size: 11px; margin: 0; line-height: 1.5;">
                                Cet email concerne votre commande {order.order_number}
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        # Préparer les images embarquées pour le logo
        embedded_images = []
        if logo_data:
            img_bytes, content_type, _ = logo_data
            embedded_images.append((img_bytes, "logo", content_type))

        msg = self._create_message(
            to_email=to_email,
            subject=f"Remboursement confirmé - {order.order_number}",
            html_content=html,
            embedded_images=embedded_images if embedded_images else None
        )

        self._send(msg)


# Singleton
email_service = EmailService()


# Fonctions helper pour les background tasks
async def send_confirmation_email(to_email, customer_name, order, tickets, pdf_path):
    """Helper pour background tasks"""
    await email_service.send_confirmation(to_email, customer_name, order, tickets, pdf_path)


async def send_reminder_email(to_email, customer_name, order, pdf_path):
    """Helper pour background tasks"""
    await email_service.send_reminder(to_email, customer_name, order, pdf_path)


async def send_refund_email(to_email, customer_name, order, amount):
    """Helper pour background tasks"""
    await email_service.send_refund(to_email, customer_name, order, amount)
