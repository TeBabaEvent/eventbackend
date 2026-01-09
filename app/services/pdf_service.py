"""
Service de génération de PDF pour les billets électroniques
Design Premium avec WeasyPrint - BABA Event
"""
import os
import base64
import asyncio
from datetime import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor
import logging

from jinja2 import Environment, FileSystemLoader

# WeasyPrint lazy import - évite le crash au démarrage si les libs système manquent
_weasyprint_html = None
_weasyprint_css = None  # CSS stylesheet réutilisable (cache)
_weasyprint_available = None

def _configure_library_paths():
    """Configure les chemins des bibliothèques si nécessaire (legacy, pour compatibilité)."""
    # Sur Ubuntu/Debian, les libs sont trouvées automatiquement via apt
    # Cette fonction est gardée pour compatibilité avec d'autres environnements
    extra_lib_paths = [
        "/usr/local/lib",
    ]
    
    current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    new_paths = [p for p in extra_lib_paths if p not in current_ld_path and os.path.exists(p)]
    
    if new_paths:
        os.environ["LD_LIBRARY_PATH"] = ":".join(new_paths) + ":" + current_ld_path
        logging.getLogger(__name__).debug(f"LD_LIBRARY_PATH configuré: {os.environ['LD_LIBRARY_PATH'][:100]}...")

def _get_weasyprint():
    """Import WeasyPrint lazily pour éviter le crash au démarrage."""
    global _weasyprint_html, _weasyprint_css, _weasyprint_available
    if _weasyprint_available is None:
        # Configurer les chemins avant l'import
        _configure_library_paths()
        
        # Réduire le bruit des logs fontTools AVANT l'import de WeasyPrint
        for lib in ["fontTools", "fontTools.subset", "fontTools.ttLib", 
                    "fontTools.subset.timer", "fontTools.ttLib.ttFont"]:
            logging.getLogger(lib).setLevel(logging.ERROR)
        
        try:
            from weasyprint import HTML, CSS
            _weasyprint_html = HTML
            _weasyprint_css = CSS
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
    return _weasyprint_html, _weasyprint_css


def prewarm_weasyprint():
    """
    Pré-charge WeasyPrint au démarrage de l'application.
    Génère un mini PDF vide pour initialiser les caches internes.
    Appelé depuis main.py au startup.
    """
    try:
        HTML, _ = _get_weasyprint()
        # Générer un mini PDF pour "réchauffer" le moteur
        HTML(string="<html><body>warm</body></html>").write_pdf()
        logging.getLogger(__name__).info("✅ WeasyPrint pré-chargé avec succès")
    except Exception as e:
        logging.getLogger(__name__).warning(f"WeasyPrint prewarm échoué: {e}")

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
# Augmenté pour permettre la génération parallèle de plusieurs PDFs
_executor = ThreadPoolExecutor(max_workers=8)

# ============================================
# HELPERS
# ============================================

MOIS_FR = {
    1: 'janvier', 2: 'février', 3: 'mars', 4: 'avril', 
    5: 'mai', 6: 'juin', 7: 'juillet', 8: 'août', 
    9: 'septembre', 10: 'octobre', 11: 'novembre', 12: 'décembre'
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
    HTML, _ = _get_weasyprint()
    HTML(string=html_content).write_pdf(filepath)
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
    
    PDFs are generated in PARALLEL for better performance.
    
    Args:
        tickets: List of tickets to generate PDFs for
        order: The order containing the tickets
    
    Returns:
        List[str]: List of paths to the generated PDF files
    """
    if not tickets:
        raise ValueError("No tickets provided")
    
    logger.info(f"Generating {len(tickets)} individual ticket PDFs for order {order.order_number}")
    
    total_tickets = len(tickets)
    
    # Générer tous les PDFs en parallèle pour de meilleures performances
    tasks = [
        generate_single_ticket_pdf(ticket, order, index, total_tickets)
        for index, ticket in enumerate(tickets, start=1)
    ]
    
    pdf_paths = await asyncio.gather(*tasks)
    
    logger.info(f"Generated {len(pdf_paths)} individual ticket PDFs for order {order.order_number}")
    return list(pdf_paths)


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
