"""
Cover Letter Module — Phase 3

Generates a 3-paragraph cover letter via Claude and exports it as a PDF using weasyprint.
"""

import logging
import os
import re
from pathlib import Path

import anthropic

from modules.job_intelligence import _load_profile, _candidate_summary, _parse_json
from prompts.cover_letter import COVER_LETTER_SYSTEM, COVER_LETTER_USER

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def generate_text(company: str, role: str, jd_summary: str, profile_path: str = "applicant_profile.json") -> str:
    """Generate cover letter text via Claude. Returns plain text (3 paragraphs)."""
    profile = _load_profile(profile_path)
    candidate_summary = _candidate_summary(profile)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=COVER_LETTER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": COVER_LETTER_USER.format(
                    candidate_summary=candidate_summary,
                    company=company,
                    role=role,
                    jd_summary=jd_summary,
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def export_pdf(text: str, output_path: str) -> str:
    """Render plain-text cover letter to PDF using reportlab. Returns the output path."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.enums import TA_JUSTIFY
    except ImportError:
        raise RuntimeError("reportlab is not installed. Run: uv add reportlab")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=3 * cm,
        rightMargin=3 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    style = ParagraphStyle(
        "body",
        fontName="Times-Roman",
        fontSize=12,
        leading=18,
        alignment=TA_JUSTIFY,
    )

    story = []
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace("\n", " "), style))
            story.append(Spacer(1, 0.4 * cm))

    doc.build(story)
    log.info("Cover letter PDF saved: %s", output_path)
    return output_path


def generate(
    company: str,
    role: str,
    jd_summary: str,
    output_path: str,
    profile_path: str = "applicant_profile.json",
) -> tuple[str, str]:
    """
    Full pipeline: generate text, export PDF.
    Returns (cover_letter_text, pdf_path).
    """
    text = generate_text(company, role, jd_summary, profile_path)
    pdf_path = export_pdf(text, output_path)
    return text, pdf_path
