# Google setup

You need two Google credentials:

| Credential | Used for |
|---|---|
| **Service account** | The server reading and writing your Google Sheet |
| **OAuth client** | You signing in to the app with Google |

Both live in the same Google Cloud project.

## A. Create the project and enable the Sheets API

1. Open <https://console.cloud.google.com/projectcreate> and create a project, e.g. `daily-tracker`.
2. Open <https://console.cloud.google.com/apis/library/sheets.googleapis.com> (with the new project selected) and click **Enable**.

## B. Service account (sheet access)

1. Go to **IAM & Admin → Service Accounts → Create service account**: <https://console.cloud.google.com/iam-admin/serviceaccounts>
   - Name: `daily-tracker`. It needs **no** project roles, so skip the optional steps.
2. Open the new service account → **Keys → Add key → Create new key → JSON**. A `.json` file downloads.
   Keep it secret, and never commit it (`.gitignore` already blocks `service-account*.json`).
3. Copy the `client_email` from that file (it looks like `daily-tracker@<project>.iam.gserviceaccount.com`).
4. Open your **Daily** Google Sheet → **Share** → paste that email → **Editor** → untick "Notify" → Share.
5. Note the Sheet ID from its URL: `https://docs.google.com/spreadsheets/d/`**`1AbC…xyz`**`/edit`.

For Render, paste the **entire JSON file content** into `GOOGLE_SERVICE_ACCOUNT_JSON`.
If the dashboard has trouble with multi-line values, use base64 instead:

```bash
base64 -w0 service-account.json      # Linux
base64 -i service-account.json       # macOS
```

## C. OAuth client (Google sign-in)

1. **APIs & Services → OAuth consent screen**: <https://console.cloud.google.com/apis/credentials/consent>
   - User type: **External** → app name `Daily Tracker` → your email as support and developer contact.
   - Scopes: none extra needed (`openid`, `email` and `profile` are default).
   - **Test users:** add your Gmail address. While the app is in *Testing* status, only test users can sign in, which is exactly what you want for a personal tool.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**: <https://console.cloud.google.com/apis/credentials>
   - Application type: **Web application**
   - Authorized redirect URIs:
     - `https://<your-render-app>.onrender.com/auth/callback`
     - `http://localhost:5000/auth/callback` (local dev)
3. Copy the **Client ID** and **Client secret** into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

## D. Check it

```bash
python -m scripts.check_setup
```

Expected output:

```
✓ configuration looks valid
✓ service account: daily-tracker@….iam.gserviceaccount.com
✓ storage reachable (sheets); 13 tab(s): May-26, Jun-26, …
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Google Sheet not found" | Wrong `GOOGLE_SHEET_ID`, or the sheet isn't shared with the service account email |
| `redirect_uri_mismatch` on sign-in | The exact callback URL (https, no trailing slash) must be in the OAuth client's redirect URIs |
| "This Google account is not allowed" | Add the address to `ALLOWED_EMAILS` |
| "Access blocked: app has not completed verification" | Add your account under OAuth consent screen → Test users |
| The sheet is an uploaded `.xlsx` | In Google Sheets: **File → Save as Google Sheets**, then use the new sheet's ID |
