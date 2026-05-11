# 🤖 AI Daily Briefing Agent

A production-ready autonomous agent that reads your Gmail and Google Calendar daily, uses Gemini AI to generate an intelligent briefing, and sends it to your Telegram every morning.

```
Good Morning ☀️ Monday, January 15, 2024

📅 Meetings Today
• 10:00 AM – Product Sync (Google Meet | 3 attendees)
• 2:30 PM – Client Call (Zoom | 5 attendees)
⚠️ Conflict: Product Sync and Pre-Call overlap by 15 min

📧 Important Emails
1. [URGENT] AWS Billing Alert – $340 charge, payment due tomorrow
2. Internship interview scheduled – Reply by Friday to confirm
3. Hackathon deadline extended to Jan 20 – Extra 3 days available

⚠️ Priority Actions
• Reply to recruiter (Priya Singh) about interview slot
• Check AWS billing dashboard – unusual charge detected
• Prepare demo slides before 2:30 PM client call

🧠 AI Suggestion
Focus on the billing alert and interview reply before your 10 AM sync.
Block 12–2 PM for deep work on the demo presentation.
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     main.py                             │
│              (CLI entry point)                          │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              BriefingAgent                              │
│         (agents/briefing_agent.py)                      │
│   Orchestrates pipeline, handles errors & retries       │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌───▼────────────┐
│GmailService │ │CalendarSvc │ │ AIOrchestrator │
│             │ │            │ │                │
│OAuth2 auth  │ │OAuth2 auth │ │ GeminiProvider │
│Fetch emails │ │Fetch events│ │ OpenAIFallback │
│Categorize   │ │Detect conf.│ │                │
└─────────────┘ └────────────┘ └───────┬────────┘
                                        │
                               ┌────────▼────────┐
                               │ TelegramService  │
                               │ Send formatted  │
                               │ briefing message│
                               └─────────────────┘
```

### Folder Structure

```
ai-briefing-agent/
├── main.py                          # CLI entry point
├── requirements.txt
├── Dockerfile
├── .env.example
├── .gitignore
├── README.md
│
├── src/
│   ├── config.py                    # Pydantic settings (all env vars)
│   ├── logger.py                    # Structured logging (JSON for prod)
│   ├── scheduler.py                 # APScheduler cron runner
│   │
│   ├── agents/
│   │   └── briefing_agent.py        # Core orchestration agent
│   │
│   ├── services/
│   │   ├── gmail_service.py         # Gmail OAuth2 + email fetching
│   │   ├── calendar_service.py      # Google Calendar integration
│   │   ├── ai_summary.py            # Gemini/OpenAI summarization
│   │   └── telegram_service.py      # Telegram Bot API
│   │
│   ├── prompts/
│   │   └── briefing_prompt.py       # AI prompt templates
│   │
│   └── utils/
│       ├── retry.py                 # Exponential backoff decorator
│       └── date_utils.py            # Timezone-aware date helpers
│
├── config/
│   ├── credentials.json             # Google OAuth2 credentials (gitignored)
│   └── token.json                   # OAuth2 token (gitignored)
│
├── tests/
│   ├── test_gmail_service.py
│   ├── test_briefing_agent.py
│   └── test_calendar_service.py
│
└── scripts/
    └── deploy_cloud_run.sh          # GCP deployment script
```

---

## Setup Guide

### Step 1: Clone and install

```bash
git clone https://github.com/yourname/ai-briefing-agent.git
cd ai-briefing-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Step 2: Google Cloud Console Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable these APIs:
   - **Gmail API**: APIs & Services → Library → "Gmail API" → Enable
   - **Google Calendar API**: APIs & Services → Library → "Google Calendar API" → Enable
4. Create OAuth2 credentials:
   - APIs & Services → Credentials → Create Credentials → **OAuth client ID**
   - Application type: **Desktop app**
   - Name: "AI Briefing Agent"
   - Download the JSON → save as `config/credentials.json`
5. Configure OAuth consent screen:
   - APIs & Services → OAuth consent screen
   - User type: External (for personal use)
   - Add your email as a test user
   - Scopes: `gmail.readonly`, `calendar.readonly`

### Step 3: Get Gemini API Key

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create API key → copy it
3. Add to `.env`: `GEMINI_API_KEY=your-key-here`

### Step 4: Create Telegram Bot

1. Open Telegram → search for `@BotFather`
2. Send `/newbot` → follow prompts → copy the **bot token**
3. Add to `.env`: `TELEGRAM_BOT_TOKEN=1234567890:ABC...`
4. Get your chat ID:
   - Send any message to your new bot
   - Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find `"chat": {"id": 123456789}` → copy that number
5. Add to `.env`: `TELEGRAM_CHAT_ID=123456789`

### Step 5: First-time OAuth2 setup

```bash
# Opens browser for Google sign-in (one-time only)
python main.py --setup-oauth
```

### Step 6: Test everything

```bash
# Test Telegram bot
python main.py --test-telegram

# Run briefing now
python main.py --run-now

# Start daily scheduler (7 AM by default)
python main.py --schedule
```

---

## Deployment Options

### Option A: GitHub Actions (Free, Recommended for beginners)

1. Push code to GitHub
2. Add these GitHub Secrets (Settings → Secrets → Actions):
   ```
   GOOGLE_CLIENT_ID
   GOOGLE_CLIENT_SECRET
   GOOGLE_TOKEN_JSON        # base64: base64 -w 0 config/token.json
   GOOGLE_CREDENTIALS_JSON  # base64: base64 -w 0 config/credentials.json
   GEMINI_API_KEY
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
   ```
3. The workflow (`.github/workflows/daily-briefing.yml`) runs at 7 AM IST automatically.

### Option B: Google Cloud Run Jobs (Production)

```bash
export GCP_PROJECT_ID=your-project-id
export GEMINI_API_KEY=your-key
export TELEGRAM_BOT_TOKEN=your-token
export TELEGRAM_CHAT_ID=your-chat-id

chmod +x scripts/deploy_cloud_run.sh
./scripts/deploy_cloud_run.sh
```

This:
- Builds and pushes Docker image to Container Registry
- Deploys as a Cloud Run Job (stateless, pay-per-execution)
- Sets up Cloud Scheduler to trigger at 7 AM IST daily
- Stores all secrets in Secret Manager

### Option C: Local scheduler (Raspberry Pi / always-on machine)

```bash
python main.py --schedule
```

Runs indefinitely. Set `BRIEFING_CRON` in `.env` to your preferred time.

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | ✅ | - | OAuth2 Client ID |
| `GOOGLE_CLIENT_SECRET` | ✅ | - | OAuth2 Client Secret |
| `GEMINI_API_KEY` | ✅ | - | Google AI Studio key |
| `TELEGRAM_BOT_TOKEN` | ✅ | - | @BotFather token |
| `TELEGRAM_CHAT_ID` | ✅ | - | Your Telegram chat ID |
| `GMAIL_MAX_EMAILS` | ❌ | 20 | Max emails to fetch |
| `GMAIL_HOURS_LOOKBACK` | ❌ | 24 | Hours back to search |
| `BRIEFING_CRON` | ❌ | `0 7 * * *` | Cron schedule |
| `TIMEZONE` | ❌ | `Asia/Kolkata` | Your timezone |
| `GEMINI_MODEL` | ❌ | `gemini-1.5-flash` | AI model |
| `LOG_LEVEL` | ❌ | `INFO` | Logging verbosity |
| `ENVIRONMENT` | ❌ | `development` | dev/staging/production |

---

## Security Best Practices

1. **Never commit secrets** — `.gitignore` covers `.env`, `token.json`, `credentials.json`
2. **Use Secret Manager in production** — Never pass secrets as plain env vars in Cloud Run
3. **Minimal OAuth scopes** — Only `gmail.readonly` and `calendar.readonly`; never request write access
4. **Non-root Docker container** — The Dockerfile runs as a `briefing` user, not root
5. **Token rotation** — Google OAuth2 tokens auto-refresh; the new token is saved automatically
6. **Rate limit awareness** — All API calls have retry decorators with exponential backoff
7. **Audit logging** — All runs log start/end/errors in structured JSON (Cloud Logging compatible)

---

## Future Roadmap

### Phase 2: Intelligence Layer
- [ ] **Vector Memory**: Store email summaries in Pinecone for "what did X say last week?" queries
- [ ] **RAG Support**: Retrieve relevant past context when summarizing current emails
- [ ] **Task Extraction**: Auto-create tasks from emails with deadlines
- [ ] **Follow-up Detection**: Alert when an email hasn't been replied to in N days
- [ ] **AI Prioritization Engine**: ML model trained on your email response patterns

### Phase 3: Multi-channel
- [ ] **Slack Integration**: Send briefing to a Slack channel (`slack-sdk`)
- [ ] **WhatsApp**: Via Twilio WhatsApp API
- [ ] **Notion**: Auto-create daily briefing pages in your Notion workspace
- [ ] **Email Digest**: Send as a formatted HTML email fallback

### Phase 4: SaaS
- [ ] **Multi-user support**: Per-user OAuth tokens stored in Redis
- [ ] **Web dashboard**: React frontend to configure preferences
- [ ] **Webhook API**: Allow users to trigger briefings on-demand
- [ ] **Weekly Productivity Report**: AI-generated weekly summary

---

## Running Tests

```bash
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## Troubleshooting

**"No valid token found. Launching browser OAuth2 flow..."**
→ Run `python main.py --setup-oauth` first.

**"Telegram API error: chat not found"**
→ Send a message to your bot first, then get the chat ID from `/getUpdates`.

**"Gemini API quota exceeded"**
→ Set `OPENAI_API_KEY` as fallback, or wait for quota reset (daily).

**"OAuth2 scopes mismatch"**
→ Delete `config/token.json` and re-run `--setup-oauth` to get fresh token with all scopes.
