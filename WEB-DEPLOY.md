# Konzei Clips — website deployment (v1.2 starter)

This is a **deployment-ready starter**, not a complete production security audit. It hosts the existing Konzei editing application with Google sign-in and its private owner dashboard. It uses a **single running service instance**, a **single persistent disk**, and a **single SQLite database**. It's suitable for a private alpha with modest usage, not a high-volume SaaS launch.

## 1. Create your private GitHub repository

Make a new empty repository on https://github.com/new (for example `konzei-clips`). Extract the contents of this ZIP into a folder and run inside that folder:

```powershell
git init
git add .
git commit -m "Konzei Clips web starter"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/konzei-clips.git
git push -u origin main
```

**Never commit `.env`, account databases, user videos, service tokens or browser cookies.** The package excludes all existing user data and the `.gitignore` and `.dockerignore` protect local files.

## 2. Deploy to Railway

1. Go to https://railway.com/new and create a project from your GitHub repository. Choose the `main` branch. Railway detects the included Dockerfile.
2. BEFORE inviting other users, add a persistent **volume mounted at `/app/data`**. This is required: user accounts, videos, exports, sessions, and owner binding are all in this directory. Without a volume they are lost on deploy/restart.
3. Configure Railway service Variables (do not commit secret values):
   - `KONZEI_PUBLIC_MODE=1`
   - `KONZEI_GOOGLE_CLIENT_ID=...apps.googleusercontent.com` (your own Google Web Client ID)
   - `KONZEI_OWNER_EMAIL=...` (your verified owner Gmail address)
   - `KONZEI_DATA_DIR=/app/data`
   - `KONZEI_MAX_UPLOAD_GB=1` (start with a small limit; current parsing expects whole GB)
   - `KONZEI_MAX_ACTIVE_JOBS=2` (avoid easy overload)
   Railway injects `PORT`; the container listens on it automatically.
4. In Networking, generate your HTTPS Railway domain (or connect a custom domain).
5. In Google Cloud Console, create or edit the OAuth client, type **Web application**. Add **exactly the deployed URL origin**, e.g. `https://your-subdomain.up.railway.app` (no trailing slash or paths), to **Authorized JavaScript origins**. Also configure the OAuth consent screen. If testing mode is enabled, authorize test users.
6. Restart or redeploy and log in using the verified owner account. The owner dashboard lets you manage member access and change announcements without a deployment.

## 3. Change the site without ZIP downloads

Once Railway is linked to the repository's `main` branch, an authorized push to `main` automatically triggers a build/deploy. For safer changes, make a branch and pull request, let GitHub Actions run tests, review it, then merge. Changes to Python, CSS, HTML and JS can all go out through that pipeline; currently no hot-reload of code without a deployment is implemented.

When your ChatGPT GitHub connection has repository write access, I can help edit source files and create commits or pull requests in chat, **only as permitted by available connected tools**. I cannot silently make changes between chats or bypass a required deployment approval.

## 4. Caveats and security

- Video rendering consumes paid server CPU, RAM and storage; uploads plus render outputs take space. Watch cloud billing and set quotas before public registration.
- The current SQLite and local filesystem model cannot run on multiple replicas using the same volume. Heavy usage will need a database, object storage, and job queue/worker.
- Video exports run as in-process background threads. Deploy/restarts can interrupt active jobs. Durable jobs and a worker are needed for a more reliable public launch.
- Browser cookie extraction from your own Chrome/Edge/Firefox is **disabled** in hosted mode to protect the server and user sessions. Google login for Konzei **does not** authenticate server-side YouTube downloads. Uploading your own video files works. Some public URL imports may work via yt-dlp; YouTube may refuse them. Never send your browser cookies to a hosted server as a workaround.
- The owner account is granted by verified Google account and backend configuration. `KONZEI_OWNER_EMAIL` is private, not sent to members by API. Treat your Google account as a critical admin account and use two-factor authentication.
- For real users, add privacy/terms disclosures, monitoring, rate limiting, abuse prevention, storage limits, retention/deletion policy, billing controls, backups, and security review before public launch. `X-Frame-Options` and other baseline headers do not replace a security audit.
- The deployment package contains **no live credentials, data directory, or users' projects**. Migrating local accounts or projects to the cloud requires a planned export/import and backup process (do not upload private database files into GitHub).

## 5. Local development

Works just like v1.1: `pip install -r requirements.txt`, `python app.py`, then visit http://127.0.0.1:8765 after setting up `.env`. Google Authorized JavaScript origins must include the local origin too. Docker-based localhost testing is possible with Docker installed, a local `.env` file, and `docker run -p 8765:8765 --env-file .env -e KONZEI_PUBLIC_MODE=0 -e KONZEI_DATA_DIR=/app/data ...`.
