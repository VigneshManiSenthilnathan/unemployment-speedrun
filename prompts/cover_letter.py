"""Claude prompt templates for cover letter generation."""

COVER_LETTER_SYSTEM = """\
You are a professional cover letter writer. Write compelling, concise, authentic cover letters \
for job applications. Do not use generic filler phrases. Be direct and specific.\
"""

COVER_LETTER_USER = """\
Write a 3-paragraph cover letter for the following application.

Applicant:
{candidate_summary}

Job:
Company: {company}
Role: {role}
Job Description Summary: {jd_summary}

Instructions:
- Paragraph 1 (2-3 sentences): Hook — why this company and role specifically excite the applicant.
- Paragraph 2 (3-4 sentences): The strongest 2-3 relevant experiences/skills that make the applicant a strong fit.
- Paragraph 3 (1-2 sentences): Confident close, expressing eagerness to contribute.
- Do NOT include salutation or sign-off lines — just the 3 paragraphs.
- Do NOT use phrases like "I am writing to express my interest" or "I would be a great fit".
- Be specific, reference real details from the JD summary.
- Output plain text only, no markdown.
"""
