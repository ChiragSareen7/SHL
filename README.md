# SHL Assessment Advisor

A conversational AI agent that helps hiring managers find the right SHL assessments for any role.

---

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your GROQ_API_KEY to .env

uvicorn app.main:app --port 8000
```

---

## Endpoints

### `GET /health`
```json
{ "status": "ok" }
```

### `POST /chat`

**Request**
```json
{
  "messages": [
    { "role": "user", "content": "I need to hire a senior Java engineer." },
    { "role": "assistant", "content": "..." },
    { "role": "user", "content": "Add a cognitive test as well." }
  ]
}
```

Send the full conversation history on every request — the service is stateless.

**Response**
```json
{
  "reply": "string",
  "recommendations": [
    {
      "name": "string",
      "url": "string",
      "test_type": "string"
    }
  ],
  "end_of_conversation": false
}
```

`recommendations` is `null` when the agent is still asking clarifying questions.  
`end_of_conversation` is `true` when the user confirms they are done.  
Maximum 8 turns per session.

---

## Deploy

Push to GitHub, connect to [Render](https://render.com), set:
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Env var:** `GROQ_API_KEY`
