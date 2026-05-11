"""
prompts/briefing_prompt.py - Prompt templates for Gemini AI summarization.

Keeping prompts in a dedicated module makes them:
  - Easy to iterate and A/B test
  - Version-controllable
  - Swappable without touching business logic
"""

import json
from datetime import datetime
from typing import Dict, List, Any

from src.services.calendar_service import CalendarEvent, ConflictInfo
from src.services.gmail_service import EmailItem
from src.utils.date_utils import now_local


# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a highly intelligent executive assistant AI.

Your role is to produce a clear, concise, and actionable daily briefing.

Rules:
- Be direct and professional
- Prioritize urgency and time-sensitivity
- Extract concrete action items
- Flag scheduling conflicts clearly
- Highlight overdue tasks prominently
- Suggest a smart focus strategy
- Keep total response under 3500 characters
- Use plain text only
- Do NOT use HTML
- Do NOT use markdown
- Use emojis sparingly
- Never invent information

Formatting Rules (STRICT):
- Use box-drawing characters for the header: ╔════╗ / ║ / ╚════╝
- Use ── separators under each section heading
- Bullet items use • with sub-items using → on the next line (indented 2 spaces)
- Timestamps use 🕒 prefix inline
- Number action items as 1. 2. 3.
- Section headers use a single emoji + ALL CAPS label (e.g. 📅 TODAY'S SCHEDULE)
"""


def build_briefing_prompt(
    emails: Dict[str, List[EmailItem]],
    events: List[CalendarEvent],
    conflicts: List[ConflictInfo],
    tasks: List[Any],
    task_summary: Any,
) -> str:
    """
    Builds the user-facing prompt with all data serialized as JSON.
    Gemini processes this structured data to generate the briefing.
    
    emails parameter is now grouped by priority:
    {
        "important": [...],
        "low_priority": [...],
        "useless": [...],
        "spam": [...],
        "general": [...]
    }
    
    tasks parameter is a list of TaskItem objects.
    task_summary parameter contains TaskSummary statistics.
    """
    now = now_local()
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    # Group emails by priority and cap each category
    grouped_email_data = {}
    for category, email_list in emails.items():
        grouped_email_data[category] = [
            e.to_dict() for e in email_list[:10]
        ]

    event_data = [e.to_dict() for e in events]
    conflict_data = [
        {
            "event_a": c.event_a.title,
            "event_b": c.event_b.title,
            "overlap_minutes": c.overlap_minutes,
        }
        for c in conflicts
    ]

    # ── Process Tasks ──────────────────────────────────────────────────────
    tasks_text = ""

    if tasks:
        overdue = [t for t in tasks if t.is_overdue]
        today = [t for t in tasks if t.is_today]
        upcoming = [
            t for t in tasks
            if not t.is_overdue and not t.is_today
        ]

        tasks_text += "\n=== PENDING TASKS ===\n"

        tasks_text += (
            f"\nSummary:"
            f"\n- Total Pending: {task_summary.total_pending}"
            f"\n- Due Today: {task_summary.today_tasks}"
            f"\n- Upcoming: {task_summary.upcoming_tasks}"
            f"\n- Overdue: {task_summary.overdue_tasks}\n"
        )

        if overdue:
            tasks_text += "\nOVERDUE TASKS (High Priority):\n"
            for t in overdue[:5]:
                due_date = str(t.due_date) if t.due_date else "No date"
                tasks_text += f"• {t.title} (Due: {due_date})\n"

        if today:
            tasks_text += "\nDUE TODAY:\n"
            for t in today[:5]:
                tasks_text += f"• {t.title}\n"

        if upcoming:
            tasks_text += "\nUPCOMING TASKS:\n"
            for t in upcoming[:5]:
                due_date = str(t.due_date) if t.due_date else "No date"
                tasks_text += f"• {t.title} (Due: {due_date})\n"

    else:
        tasks_text = "\n=== PENDING TASKS ===\nNo pending tasks.\n"

    prompt = f"""Today is {date_str} at {time_str}.

Generate a clean plain-text daily briefing based on the data below.

=== TODAY'S CALENDAR EVENTS ===
{json.dumps(event_data, indent=2, default=str)}

=== SCHEDULING CONFLICTS ===
{json.dumps(conflict_data, indent=2) if conflict_data else "None detected"}

=== RECENT EMAILS (Grouped by Priority) ===
{json.dumps(grouped_email_data, indent=2, default=str)}

{tasks_text}

=== INSTRUCTIONS ===
Produce a structured briefing with these exact sections using this layout:

╔════════════════════════════╗
   🌅 DAILY AI BRIEFING
   {date_str}
╚════════════════════════════╝

📅 TODAY'S SCHEDULE
──────────────────
[List each event with • prefix. Flag conflicts with ⚠️]
✅ No scheduling conflicts detected   (or list conflicts with ⚠️)

📧 EMAIL SUMMARY
──────────────────
🚨 High Priority
[Top 3-5 urgent emails from "important" category, each as:]
• Sender — Subject
  → One-line summary
  🕒 Time

📌 Low Priority
[GitHub, CI/CD, workflow emails — brief • list, no timestamps needed]

📨 General Updates
• [Count] additional emails
• Includes [brief description]

📝 TASKS & ACTION ITEMS
──────────────────
[If tasks exist, include:]
⚠️ OVERDUE TASKS (if any)
• [task with due date]

📌 DUE TODAY (if any)
• [task]

⏳ UPCOMING (if any)
• [task with due date]

[Then extract concrete action items:]
1. First action (from emails/tasks/calendar)
2. Second action
3. Third action

🧠 AI INSIGHT
──────────────────
[One smart focus tip, 2-3 sentences max, word-wrapped at ~55 chars]
[Consider task deadlines vs meeting schedule]

Start the response with the ╔╗ box header exactly as shown above.
Ensure overdue tasks are flagged prominently as ⚠️.
"""
    return prompt


# ── Email ranking prompt (AI re-ranks important emails) ──────────────────────

EMAIL_RANKING_PROMPT = """
You are an email priority expert. Given this list of "important" emails, 
select and rank the TOP 5 MOST ACTIONABLE emails that the user should focus on TODAY.

Important means:
- Requires immediate action or response
- Has a deadline mentioned
- Involves a meeting, payment, or critical decision
- From a key stakeholder or manager
- Is security/account related

Return ONLY a JSON array with this structure:
[
  {{
    "subject": "email subject",
    "action": "what the user should do (1 sentence)"
  }},
  ...
]

Emails to rank:
{emails_json}
"""


def build_email_ranking_prompt(important_emails: List[EmailItem]) -> str:
    """
    Builds prompt for Gemini to re-rank important emails by actionability.
    """
    emails_json = json.dumps(
        [
            {
                "subject": e.subject,
                "from": e.sender,
                "snippet": e.snippet,
                "category": e.category,
            }
            for e in important_emails[:15]
        ],
        indent=2,
        default=str,
    )
    return EMAIL_RANKING_PROMPT.format(emails_json=emails_json)


# ── Email categorization prompt (used for enhanced AI categorization) ──────────

CATEGORIZATION_PROMPT = """
You are an email triage assistant. Given the email below, categorize it as one of:
[important, low_priority, useless, spam, general]

Also extract:
- action_required: true/false
- follow_up_needed: true/false  
- deadline_mentioned: the deadline if any (or null)
- task_summary: 1-sentence summary of what the user needs to do (or null)

Respond ONLY in valid JSON. No markdown, no explanation.

Email:
Subject: {subject}
From: {sender}
Body: {body}
"""


def build_categorization_prompt(email: EmailItem) -> str:
    return CATEGORIZATION_PROMPT.format(
        subject=email.subject,
        sender=email.sender,
        body=email.body_text[:800],
    )


# ── Weekly report prompt (future feature) ─────────────────────────────────────

WEEKLY_REPORT_PROMPT = """
You are a productivity analyst. Based on this week's activity data, generate a
weekly productivity report with:
1. Summary of meetings attended
2. Key email threads and outcomes
3. Task completion rate
4. Productivity score (1-10) with reasoning
5. Recommendations for next week

Data:
{weekly_data}

Format as clean plain text for Telegram. Be specific and actionable.
"""


# ── Task extraction prompt (future feature) ────────────────────────────────────

TASK_EXTRACTION_PROMPT = """
Extract all action items and tasks from the following email.
Return as a JSON array of objects with fields:
- task: string (what to do)
- priority: "high" | "medium" | "low"
- due_date: string or null
- assignee: "me" | other_name

Email:
Subject: {subject}
Body: {body}

Return ONLY valid JSON array. No markdown.
"""
