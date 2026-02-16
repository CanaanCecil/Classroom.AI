# Classroom AI Assistant (MVP)

Teacher-controlled AI Q&A platform for K-12 classrooms.

## Features

- Student interface with classroom join code
- Named or anonymous student questions
- AI response generation with teacher-selected tone and grade level
- Teacher dashboard with real-time feed of all interactions
- Teacher controls:
  - Turn AI on/off
  - Restrict topic (curriculum mode)
  - Approve/hide responses
  - Flag inaccurate responses
  - Broadcast selected Q&A to class
- Analytics:
  - Common confusion keywords
  - Most asked concepts
  - Student support signal (question volume)
  - Weekly CSV export
- Safety:
  - Inappropriate content filter
  - Transcript archive in SQLite
  - No external browsing from AI logic

## Quick start

```bash
python3 app.py
```

Open:
- Student view: http://localhost:8000/
- Teacher dashboard: http://localhost:8000/teacher

Default classroom join code: `ABC123`

## Environment variables

- `OPENAI_API_KEY` (optional): if set, the app will call OpenAI Responses API via HTTP.
- `PORT` (optional): default `8000`

If no API key is provided or call fails, the app falls back to a local safe explainer.


### Preview / routing notes

The app serves the student UI for these paths as well: `/`, `/index.html`, `/student`, and `/preview`.
This avoids "Not Found" errors in hosted preview environments that use non-root entry paths.

Health check endpoint: `/health`

## Notes

This is an MVP prototype intended for pilot validation and product iteration.
