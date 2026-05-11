# 🤖 AI Daily Briefing Agent
### AWS Lambda · EventBridge Scheduler · Gemini AI · Telegram

> An autonomous, serverless productivity assistant that reads your **Gmail**, **Google Calendar**, and **Google Tasks** — generates an AI-powered daily briefing using **Gemini** — and delivers it straight to your **Telegram** chat, fully automated on **AWS Lambda**.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📧 Gmail Integration | Fetches unread important emails, auto-categorized |
| 📅 Google Calendar | Reads today's meetings, detects scheduling conflicts |
| ✅ Google Tasks | Retrieves pending and overdue tasks |
| 🧠 Gemini AI | Smart, concise, actionable daily briefing |
| 📲 Telegram Delivery | HTML-formatted message sent to your chat |
| ☁️ AWS Lambda | Serverless, stateless, pay-per-execution |
| ⏰ EventBridge Scheduler | Fully automated, multiple daily triggers |
| 🔐 OAuth2 | Minimal-scope, read-only Google authentication |
| 📦 CI/CD | GitHub Actions auto-deploy pipeline |

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Amazon EventBridge Scheduler                   │
│         cron(30 1 * * ? *)  →  7:00 AM IST (daily)             │
│         cron(0 7 * * ? *)   →  12:30 PM IST (midday refresh)   │
└──────────────────────────────┬──────────────────────────────────┘
                               │  Trigger
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AWS Lambda Function                        │
│                  Runtime: Python 3.12 · 512 MB                  │
│             Timeout: 5 min · Handler: lambda_handler            │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                  BriefingAgent (Orchestrator)           │   │
│   │   asyncio.gather() → concurrent API fetches            │   │
│   └──────┬──────────────┬──────────────┬────────────────────┘   │
│          │              │              │                         │
│   ┌──────▼──────┐ ┌─────▼──────┐ ┌───▼────────┐               │
│   │GmailService │ │CalendarSvc │ │TaskService │               │
│   └─────────────┘ └────────────┘ └────────────┘               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
              ┌────────────────▼─────────────────┐
              │        AIOrchestrator             │
              │   GeminiProvider (primary)        │
              │   OpenAIProvider  (fallback)      │
              └────────────────┬─────────────────┘
                               │
              ┌────────────────▼─────────────────┐
              │        TelegramService            │
              │   Formatted HTML → Bot API        │
              └───────────────────────────────────┘

Secrets stored in:  AWS Systems Manager Parameter Store (SSM)
OAuth token stored: AWS SSM  (refreshed and re-saved automatically)
Logs streamed to:   Amazon CloudWatch Logs
```

---

## 📂 Project Structure

```
ai-briefing-agent/
│
├── lambda_function.py               ← AWS Lambda entry point
├── main.py                          ← Local CLI entry point
├── requirements.txt
├── Dockerfile
├── .env.example
├── .gitignore
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── config.py                    ← Pydantic settings (env vars + SSM)
│   ├── logger.py                    ← JSON logging for CloudWatch
│   ├── scheduler.py                 ← APScheduler (local mode only)
│   │
│   ├── agents/
│   │   └── briefing_agent.py        ← Core pipeline orchestrator
│   │
│   ├── services/
│   │   ├── gmail_service.py         ← Gmail OAuth2 + email fetch + categorize
│   │   ├── calendar_service.py      ← Calendar events + conflict detection
│   │   ├── google_tasks_service.py  ← Google Tasks (pending + overdue)
│   │   ├── ai_summary.py            ← Gemini / OpenAI summarization
│   │   └── telegram_service.py      ← Telegram Bot API delivery
│   │
│   ├── prompts/
│   │   └── briefing_prompt.py       ← All AI prompt templates
│   │
│   └── utils/
│       ├── retry.py                 ← @with_retry decorator (async + sync)
│       └── date_utils.py            ← Timezone-aware date helpers
│
├── config/
│   ├── credentials.json             ← Google OAuth2 client secrets (gitignored)
│   └── token.json                   ← OAuth2 token (gitignored)
│
├── tests/
│   ├── __init__.py
│   ├── test_gmail_service.py
│   ├── test_calendar_service.py
│   ├── test_tasks_service.py
│   └── test_briefing_agent.py
│
├── scripts/
│   ├── build_lambda_package.sh      ← Packages dependencies + code into zip
│   └── deploy_lambda.sh             ← Full AWS deploy (Lambda + Scheduler)
│
└── .github/
    └── workflows/
        └── deploy.yml               ← CI/CD: test → build → deploy on push
```

---

## 📧 Example Briefing Output

```
Good Morning ☀️  Monday, January 15, 2024

📅 Meetings Today
• 10:00 AM – Product Sync  (Google Meet · 4 attendees)
• 02:30 PM – Client Call   (Zoom · 6 attendees)
⚠️  Conflict: Product Sync & Pre-Call overlap by 15 min

✅ Pending Tasks
• [OVERDUE] Submit project report  (due yesterday)
• Finish Lambda deployment setup
• Review pull request from team

📧 Important Emails
1. [URGENT]  AWS billing alert – $340 charge, due tomorrow
2. [WORK]    Internship interview – please confirm slot by Friday
3. [FINANCE] Stripe invoice #1042 generated

⚠️ Priority Actions
• Pay AWS bill before end of day
• Reply to recruiter (Priya Singh) about interview slot
• Resolve scheduling conflict – reschedule or shorten Product Sync
• Submit overdue project report

🧠 AI Suggestion
Front-load the billing alert and recruiter reply before your 10 AM sync.
Block 12–2 PM for deep work — your afternoon is meeting-heavy.
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.12 |
| Serverless | AWS Lambda |
| Scheduler | Amazon EventBridge Scheduler |
| Secrets | AWS Systems Manager Parameter Store |
| Observability | Amazon CloudWatch Logs |
| Email | Gmail API v1 (OAuth2 read-only) |
| Calendar | Google Calendar API v3 (OAuth2 read-only) |
| Tasks | Google Tasks API v1 (OAuth2 read-only) |
| AI (primary) | Google Gemini 1.5 Flash |
| AI (fallback) | OpenAI GPT-4o-mini |
| Messaging | Telegram Bot API |
| CI/CD | GitHub Actions |
| Containers | Docker (local dev + packaging) |

---

## 🔐 Google Cloud Setup

### Step 1 — Create a Google Cloud Project

Go to [console.cloud.google.com](https://console.cloud.google.com) → **New Project**.

---

### Step 2 — Enable Required APIs

Navigate to **APIs & Services → Library** and enable:

- ✅ Gmail API
- ✅ Google Calendar API
- ✅ Google Tasks API

---

### Step 3 — Configure OAuth Consent Screen

**APIs & Services → OAuth consent screen**

| Field | Value |
|---|---|
| User Type | External |
| App name | AI Briefing Agent |
| Test users | Add your Gmail address |
| Scopes | `gmail.readonly` · `calendar.readonly` · `tasks.readonly` |

---

### Step 4 — Create OAuth 2.0 Credentials

**APIs & Services → Credentials → Create Credentials → OAuth client ID**

- Application type: **Desktop app**
- Name: `AI Briefing Agent`
- Download the JSON → save as `config/credentials.json`

---

### Step 5 — Run Local OAuth Flow (One-Time)

```bash
python main.py --setup-oauth
```

This opens a browser window for Google sign-in, then saves `config/token.json`.

---

## 🤖 Gemini API Key

Get your key from [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

---

## 📲 Telegram Bot Setup

1. Open Telegram → search `@BotFather` → send `/newbot`
2. Follow the prompts → copy the **bot token**
3. Send any message to your new bot, then visit:

```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

Find `"chat": {"id": 123456789}` — that is your **chat ID**.

---

## ☁️ AWS Setup

### Step 1 — Prerequisites

```bash
# Install and configure AWS CLI
pip install awscli
aws configure   # Enter Access Key, Secret, Region
```

Minimum IAM permissions needed for deployment:

```json
{
  "Effect": "Allow",
  "Action": [
    "lambda:*",
    "scheduler:*",
    "iam:PassRole",
    "ssm:PutParameter",
    "ssm:GetParameter",
    "logs:CreateLogGroup",
    "logs:DescribeLogGroups"
  ],
  "Resource": "*"
}
```

---

### Step 2 — Store Secrets in AWS SSM Parameter Store

```bash
# Required secrets
aws ssm put-parameter --name "/briefing/GEMINI_API_KEY"       --value "AIzaSy..." --type SecureString
aws ssm put-parameter --name "/briefing/TELEGRAM_BOT_TOKEN"   --value "1234:AB..." --type SecureString
aws ssm put-parameter --name "/briefing/TELEGRAM_CHAT_ID"     --value "123456789" --type SecureString
aws ssm put-parameter --name "/briefing/GOOGLE_CLIENT_ID"     --value "xxx.apps.googleusercontent.com" --type SecureString
aws ssm put-parameter --name "/briefing/GOOGLE_CLIENT_SECRET" --value "GOCSPX-..." --type SecureString

# Store the OAuth token JSON (base64-encoded)
aws ssm put-parameter \
  --name "/briefing/GOOGLE_TOKEN_JSON" \
  --value "$(base64 -w 0 config/token.json)" \
  --type SecureString
```

> **Why SSM?** Lambda functions read these at startup — no secrets in environment variables, no secrets in your codebase.

---

### Step 3 — Build the Lambda Deployment Package

```bash
chmod +x scripts/build_lambda_package.sh
./scripts/build_lambda_package.sh
```

This script:
1. Creates a clean `lambda-package/` directory
2. Installs all pip dependencies into it
3. Copies your `src/` code into it
4. Copies `lambda_function.py` into the root
5. Zips everything into `deployment.zip`

---

### Step 4 — Deploy to AWS

```bash
export AWS_REGION=ap-south-1       # Mumbai — good for IST users
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

chmod +x scripts/deploy_lambda.sh
./scripts/deploy_lambda.sh
```

This script:
- Creates the Lambda IAM execution role
- Creates or updates the Lambda function
- Sets all environment variables (non-secret config)
- Attaches the SSM read policy to the role
- Creates the EventBridge Scheduler rules

---

### Step 5 — Test the Lambda Manually

```bash
aws lambda invoke \
  --function-name ai-daily-briefing \
  --payload '{}' \
  --region ap-south-1 \
  response.json

cat response.json
```

---

## ⏰ EventBridge Scheduler Configuration

The deploy script creates these schedules automatically. Reference table:

| Schedule Name | Cron (UTC) | Local Time (IST) | Purpose |
|---|---|---|---|
| `briefing-morning` | `cron(30 1 * * ? *)` | 7:00 AM | Morning briefing |
| `briefing-midday` | `cron(0 7 * * ? *)` | 12:30 PM | Midday refresh |

To add more schedules manually:

```bash
aws scheduler create-schedule \
  --name "briefing-evening" \
  --schedule-expression "cron(30 13 * * ? *)" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target '{
    "Arn": "arn:aws:lambda:ap-south-1:ACCOUNT_ID:function:ai-daily-briefing",
    "RoleArn": "arn:aws:iam::ACCOUNT_ID:role/EventBridgeSchedulerRole"
  }'
```

---

## 🔄 CI/CD with GitHub Actions

### Secrets to add in GitHub (`Settings → Secrets → Actions`)

| Secret Name | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | Your AWS access key |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key |
| `AWS_REGION` | e.g. `ap-south-1` |
| `GOOGLE_TOKEN_JSON` | `base64 -w 0 config/token.json` |
| `GOOGLE_CREDENTIALS_JSON` | `base64 -w 0 config/credentials.json` |

The workflow (`.github/workflows/deploy.yml`) automatically:
- Runs `pytest` on every push
- Builds the Lambda package
- Deploys to AWS on merge to `main`

---

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## 🖥️ Local Development

```bash
# Install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # Fill in your values

# First-time Google OAuth setup
python main.py --setup-oauth

# Test Telegram connection
python main.py --test-telegram

# Run briefing immediately
python main.py --run-now

# Run with local APScheduler cron
python main.py --schedule
```

---

## 📋 Environment Variables Reference

```env
# ── Google OAuth2 ──────────────────────────────────────────────
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
GOOGLE_CREDENTIALS_PATH=config/credentials.json
GOOGLE_TOKEN_PATH=config/token.json

# ── Gemini AI ──────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy-your-gemini-key
GEMINI_MODEL=gemini-1.5-flash
GEMINI_TEMPERATURE=0.4
GEMINI_MAX_TOKENS=2048

# ── OpenAI Fallback (optional) ────────────────────────────────
OPENAI_API_KEY=

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHI...
TELEGRAM_CHAT_ID=123456789

# ── Gmail ─────────────────────────────────────────────────────
GMAIL_MAX_EMAILS=20
GMAIL_HOURS_LOOKBACK=24

# ── Calendar ──────────────────────────────────────────────────
CALENDAR_ID=primary

# ── Google Tasks ──────────────────────────────────────────────
TASKS_MAX_RESULTS=20
TASKS_INCLUDE_COMPLETED=false

# ── App ───────────────────────────────────────────────────────
TIMEZONE=Asia/Kolkata
LOG_LEVEL=INFO
ENVIRONMENT=production
BRIEFING_CRON=0 7 * * *

# ── AWS (Lambda reads from SSM — these are local-only) ────────
AWS_REGION=ap-south-1
SSM_PREFIX=/briefing
```

---

## 🔐 Security Best Practices

- **Never commit** `.env`, `token.json`, or `credentials.json` — all are in `.gitignore`
- **SSM Parameter Store** — all secrets stored encrypted with KMS, never in Lambda env vars
- **Minimal OAuth scopes** — `readonly` only; the agent can never modify your data
- **Non-root Docker** — container runs as unprivileged `briefing` user
- **Token auto-refresh** — OAuth2 token is refreshed by the SDK and re-saved to SSM automatically
- **IAM least privilege** — Lambda execution role has only `ssm:GetParameter`, `logs:*`, no extras
- **Retry + backoff** — all external API calls have `@with_retry` with exponential backoff
- **CloudWatch Logs** — all runs produce structured JSON logs; errors are immediately visible

---

## 🔮 Future Roadmap

### Phase 2 — Intelligence Layer
- [ ] AI-based task prioritization engine
- [ ] Follow-up detection (emails without replies after N days)
- [ ] Deadline extraction from email body text
- [ ] Vector memory with Pinecone for context-aware briefings (RAG)

### Phase 3 — Multi-channel Delivery
- [ ] Slack integration (`slack-sdk`)
- [ ] WhatsApp via Twilio API
- [ ] Notion — auto-create daily briefing pages
- [ ] Weekly productivity summary report

### Phase 4 — SaaS Platform
- [ ] Multi-user support with per-user OAuth tokens (DynamoDB)
- [ ] Web dashboard (React + FastAPI)
- [ ] On-demand briefing via Telegram `/briefing` command
- [ ] Custom scheduling per user

---

## 📊 AWS Cost Estimate

| Service | Usage | Estimated Monthly Cost |
|---|---|---|
| AWS Lambda | 2 invocations/day · 30 days · ~10s each | **< $0.01** |
| EventBridge Scheduler | 60 scheduled invocations/month | **< $0.01** |
| SSM Parameter Store | 6 SecureString parameters | **Free tier** |
| CloudWatch Logs | ~1 MB logs/month | **Free tier** |
| **Total** | | **~$0.00 – $0.05/month** |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/slack-integration`
3. Commit with clear messages: `git commit -m "feat: add Slack delivery service"`
4. Push and open a Pull Request

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

> Built with Python · Powered by Gemini AI · Deployed on AWS Lambda