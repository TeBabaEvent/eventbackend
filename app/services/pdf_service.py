"""
Service de génération de PDF pour les billets électroniques
Design Premium avec WeasyPrint - BABA Event
"""
import os
import io
import base64
import asyncio
from datetime import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor
import logging

from jinja2 import Environment, FileSystemLoader

# WeasyPrint lazy import - évite le crash au démarrage si les libs système manquent
_weasyprint_html = None
_weasyprint_available = None

def _configure_library_paths():
    """Configure les chemins des bibliothèques pour Nix/Railway."""
    nix_lib_paths = [
        "/root/.nix-profile/lib",
        "/nix/var/nix/profiles/default/lib",
    ]
    
    current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    new_paths = [p for p in nix_lib_paths if p not in current_ld_path and os.path.exists(p)]
    
    if new_paths:
        os.environ["LD_LIBRARY_PATH"] = ":".join(new_paths) + ":" + current_ld_path
        logging.getLogger(__name__).info(f"LD_LIBRARY_PATH configuré: {os.environ['LD_LIBRARY_PATH'][:100]}...")

def _get_weasyprint():
    """Import WeasyPrint lazily pour éviter le crash au démarrage."""
    global _weasyprint_html, _weasyprint_available
    if _weasyprint_available is None:
        # Configurer les chemins avant l'import
        _configure_library_paths()
        
        try:
            from weasyprint import HTML
            _weasyprint_html = HTML
            _weasyprint_available = True
            logging.getLogger(__name__).info("WeasyPrint chargé avec succès")
        except (ImportError, OSError) as e:
            _weasyprint_available = False
            logging.getLogger(__name__).error(f"WeasyPrint non disponible: {e}")
    
    if not _weasyprint_available:
        raise RuntimeError(
            "WeasyPrint n'est pas disponible. Les dépendances système (pango, cairo, glib) "
            "ne sont pas correctement installées. La génération de PDF est désactivée."
        )
    return _weasyprint_html

from app.db.models import Ticket, Order
from app.services.ticket_service import generate_qr_image

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates', 'pdf')
STATIC_DIR = os.path.join(BASE_DIR, 'app', 'static')
PDF_OUTPUT_DIR = os.path.join(BASE_DIR, 'temp_pdfs')
LOGO_PATH = os.path.join(STATIC_DIR, 'images', 'logo.png')

# Jinja2 Environment
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=True
)

# Thread pool for sync WeasyPrint operations
_executor = ThreadPoolExecutor(max_workers=2)

# ============================================
# HELPERS
# ============================================

MOIS_FR = {
    1: 'janvier', 2: 'février', 3: 'mars', 4: 'avril', 
    5: 'mai', 6: 'juin', 7: 'juillet', 8: 'août', 
    9: 'septembre', 10: 'octobre', 11: 'novembre', 12: 'décembre'
}

MOIS_SHORT = {
    1: 'JAN', 2: 'FÉV', 3: 'MAR', 4: 'AVR', 
    5: 'MAI', 6: 'JUIN', 7: 'JUIL', 8: 'AOÛT', 
    9: 'SEPT', 10: 'OCT', 11: 'NOV', 12: 'DÉC'
}

JOURS_FR = {
    0: 'Lundi', 1: 'Mardi', 2: 'Mercredi', 3: 'Jeudi', 
    4: 'Vendredi', 5: 'Samedi', 6: 'Dimanche'
}


def _parse_date(date_str: str) -> datetime | None:
    """Parse date string to datetime object."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _format_date_full(date_str: str) -> str:
    """Format date as 'Mercredi 31 décembre 2025'."""
    dt = _parse_date(date_str)
    if not dt:
        return date_str
    return f"{JOURS_FR[dt.weekday()]} {dt.day} {MOIS_FR[dt.month]} {dt.year}"


def _get_date_parts(date_str: str) -> tuple[str, str]:
    """Get day number and short month name."""
    dt = _parse_date(date_str)
    if not dt:
        return "-", "-"
    return str(dt.day), MOIS_SHORT[dt.month]


def _generate_qr_base64(qr_data: str) -> str:
    """Generate QR code and return as base64 string."""
    try:
        qr_bytes = generate_qr_image(qr_data)
        return base64.b64encode(qr_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        return ""


def _get_logo_base64() -> str:
    """Load logo image and return as base64 string."""
    try:
        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.warning(f"Failed to load logo: {e}")
    return ""


# ============================================
# PDF GENERATION
# ============================================

def _render_pdf_sync(html_content: str, filepath: str) -> str:
    """Synchronous PDF rendering (runs in thread pool)."""
    HTML = _get_weasyprint()
    HTML(string=html_content).write_pdf(filepath)
    return filepath


async def generate_tickets_pdf(tickets: List[Ticket], order: Order) -> str:
    """
    Generate a premium PDF with order confirmation and tickets.
    Uses WeasyPrint with HTML/CSS templates for beautiful output.
    
    DEPRECATED: Use generate_individual_ticket_pdfs for individual ticket PDFs.
    """
    if not tickets:
        raise ValueError("No tickets provided")
    
    # Ensure output directory exists
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    
    filename = f"billets-{order.order_number}.pdf"
    filepath = os.path.join(PDF_OUTPUT_DIR, filename)
    
    logger.info(f"Generating PDF with WeasyPrint: {filename}")
    
    # Prepare template data
    event = order.event
    day, month_short = _get_date_parts(event.date)
    full_date = _format_date_full(event.date)
    
    # Build location string
    location = f"{event.location}, {event.city}" if event.city else event.location
    
    # Get first name for greeting
    first_name = order.customer_name.split()[0] if order.customer_name else "Client"
    
    # Generate QR codes for all tickets
    tickets_with_qr = []
    for ticket in tickets:
        tickets_with_qr.append({
            'ticket_code': ticket.ticket_code,
            'holder_name': ticket.holder_name,
            'pack_name': ticket.pack_name,
            'qr_base64': _generate_qr_base64(ticket.qr_data)
        })
    
    # Get pack items
    pack_items = order.pack_items_list or [{'quantity': 1, 'name': 'Billet'}]
    
    # Get logo as base64
    logo_base64 = _get_logo_base64()
    
    # Render template
    template = jinja_env.get_template('tickets.html')
    html_content = template.render(
        order=order,
        event=event,
        tickets=tickets_with_qr,
        first_name=first_name,
        day=day,
        month_short=month_short,
        full_date=full_date,
        location=location,
        pack_items=pack_items,
        logo_base64=logo_base64,
        current_year=datetime.now().year
    )
    
    # Generate PDF in thread pool (WeasyPrint is sync)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _render_pdf_sync, html_content, filepath)
    
    logger.info(f"PDF generated successfully: {filepath}")
    return filepath


async def generate_single_ticket_pdf(ticket: Ticket, order: Order, ticket_index: int, total_tickets: int) -> str:
    """
    Generate a professional single-page PDF for one ticket with a large centered QR code.
    
    Args:
        ticket: The ticket to generate PDF for
        order: The order containing the ticket
        ticket_index: 1-based index of this ticket (e.g., 1 of 3)
        total_tickets: Total number of tickets in the order
    
    Returns:
        str: Path to the generated PDF file
    """
    # Ensure output directory exists
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
    
    filename = f"billet-{ticket.ticket_code}.pdf"
    filepath = os.path.join(PDF_OUTPUT_DIR, filename)
    
    logger.info(f"Generating single ticket PDF: {filename}")
    
    # Prepare template data
    event = order.event
    full_date = _format_date_full(event.date)
    location = f"{event.location}, {event.city}" if event.city else event.location
    
    # Generate QR code for this ticket
    ticket_data = {
        'ticket_code': ticket.ticket_code,
        'holder_name': ticket.holder_name,
        'pack_name': ticket.pack_name,
        'qr_base64': _generate_qr_base64(ticket.qr_data)
    }
    
    # Get logo as base64
    logo_base64 = _get_logo_base64()
    
    # Render template
    template = jinja_env.get_template('single_ticket.html')
    html_content = template.render(
        ticket=ticket_data,
        order=order,
        event=event,
        full_date=full_date,
        location=location,
        logo_base64=logo_base64,
        ticket_index=ticket_index,
        total_tickets=total_tickets,
        current_year=datetime.now().year
    )
    
    # Generate PDF in thread pool (WeasyPrint is sync)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _render_pdf_sync, html_content, filepath)
    
    logger.info(f"Single ticket PDF generated: {filepath}")
    return filepath


async def generate_individual_ticket_pdfs(tickets: List[Ticket], order: Order) -> List[str]:
    """
    Generate individual PDFs for each ticket in an order.
    Each PDF contains one ticket with a large, centered QR code.
    
    Args:
        tickets: List of tickets to generate PDFs for
        order: The order containing the tickets
    
    Returns:
        List[str]: List of paths to the generated PDF files
    """
    if not tickets:
        raise ValueError("No tickets provided")
    
    logger.info(f"Generating {len(tickets)} individual ticket PDFs for order {order.order_number}")
    
    pdf_paths = []
    total_tickets = len(tickets)
    
    for index, ticket in enumerate(tickets, start=1):
        pdf_path = await generate_single_ticket_pdf(ticket, order, index, total_tickets)
        pdf_paths.append(pdf_path)
    
    logger.info(f"Generated {len(pdf_paths)} individual ticket PDFs for order {order.order_number}")
    return pdf_paths


# ============================================
# CLEANUP
# ============================================

def cleanup_old_pdfs(days_old: int = 7) -> int:
    """Remove PDF files older than specified days."""
    if not os.path.exists(PDF_OUTPUT_DIR):
        return 0

    now = datetime.now()
    count = 0

    for filename in os.listdir(PDF_OUTPUT_DIR):
        try:
            filepath = os.path.join(PDF_OUTPUT_DIR, filename)
            if not os.path.isfile(filepath):
                continue

            file_age = now - datetime.fromtimestamp(os.path.getmtime(filepath))
            if file_age.days > days_old:
                os.remove(filepath)
                count += 1
                logger.debug(f"Cleaned up old PDF: {filename}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {filename}: {e}")

    if count > 0:
        logger.info(f"Cleaned up {count} old PDF files")

    return count


def delete_pdf_file(pdf_path: str) -> bool:
    """
    Supprime un fichier PDF spécifique immédiatement.

    Utilisé pour nettoyer les PDFs temporaires après envoi d'email réussi.

    Args:
        pdf_path: Chemin absolu vers le fichier PDF à supprimer

    Returns:
        True si la suppression a réussi, False sinon
    """
    try:
        if not pdf_path or not os.path.exists(pdf_path):
            logger.warning(f"PDF file not found: {pdf_path}")
            return False

        os.remove(pdf_path)
        logger.info(f"PDF supprimé après envoi email: {os.path.basename(pdf_path)}")
        return True

    except Exception as e:
        logger.error(f"Erreur suppression PDF {pdf_path}: {e}")
        return False
