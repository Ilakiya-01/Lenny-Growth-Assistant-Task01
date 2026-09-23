# frontend

Next.js (App Router, TypeScript, Tailwind CSS) frontend for The Lenny Growth Assistant.

Setup and run instructions are in the repository root [`README.md`](../README.md).

```bash
npm install
npm run dev      # http://localhost:3000
npm run lint     # ESLint
npm run build    # production build + TypeScript check
```

The API base URL is read from `NEXT_PUBLIC_API_BASE_URL` (see `.env.local`, optional in development)
and defaults to `http://localhost:8000`.

Phase 1 contains a workspace page that verifies backend connectivity, session creation and session
message loading. The chat interface, agent activity, LLM mode toggle and Artifact Viewer arrive in
later phases.
