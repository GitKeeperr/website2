# Fix: Railway error `Directory /app/static does not exist`

This archive has the **repository root layout**. The ZIP contains `app.py`, `Dockerfile`, and `static/` directly at the top level (no enclosing `konzei-clips/` directory).

## GitHub upload

1. Extract this ZIP **on your computer**. Do not upload the ZIP file itself as the website source.
2. In your GitHub repository, ensure that `app.py`, `Dockerfile`, and `static/` all exist at the **same top level**. Inside `static/`, verify `index.html`, `app.js`, and `style.css` are present. Upload/commit the missing files.
3. In Railway > website2 > Settings > Build, confirm Railway is building the repository root (or set **Root Directory** to the directory containing both `app.py` and `static/`). Use the included `Dockerfile`.
4. In Railway, redeploy the **new commit**. The Dockerfile now checks frontend files while building, so a missing `static/` fails early.
5. Mount your persistent Railway volume only at `/app/data`, **not** at `/app` or `/app/static`, to avoid obscuring deployed source files.

**Important:** Updating the ZIP on your computer does NOT update GitHub or Railway until you push the files. Keep your `.env`, tokens, cookies, and user data out of GitHub. Use Railway Variables for secrets.

If the same error remains, check the deployment's **commit hash**, Railway Root Directory, and volume mount path. Send a screenshot of the GitHub repo root and Railway Settings > Build if needed.
