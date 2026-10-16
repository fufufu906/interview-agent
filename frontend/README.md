# Interview Agent Frontend

Vue 3 + TypeScript + Vite. Requires Node.js 24 and npm.

```bash
npm ci
npm run dev
npm run build
node --test tests/folderImport.test.cjs
```

The development server binds 127.0.0.1:5173 and proxies /api and /health to 127.0.0.1:8000. Override the target with the MIANSHI_API_URL process environment variable when starting Vite. Chat API keys belong only in backend/.env.

Only profile and session identifiers are stored in localStorage. Unsubmitted answers remain in page memory. Actual answers, reviews and generated suggestions are separate records. Candidate replies, suggested answers and the citation area are independently collapsible.
