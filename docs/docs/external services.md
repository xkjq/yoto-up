## External services used by Yoto-UP

This document lists third-party hosts and services the project uses or may contact at runtime, why they are used, and the relevant endpoints.

### Quick inventory

- Yoto API (primary service): https://api.yotoplay.com
- Yoto OAuth / Authorization: https://login.yotoplay.com (authorization code + PKCE and token endpoints)
- Local loopback redirect server (default `http://localhost:8550/oauth_callback`) used to receive the OAuth authorization code
- YotoIcons (icon discovery / scraping): https://www.yotoicons.com
- iTunes Search API (cover art lookup): https://itunes.apple.com/search
- NLTK data downloads (punkt, stopwords) — external NLTK servers
- Asciinema embeds used in the docs: https://asciinema.org
- GitHub (repo and releases): https://github.com/xkjq/yoto-up

## Purpose and main endpoints

- Yoto API (api.yotoplay.com)
	- Purpose: content management (get/create/update/delete cards), media upload/transcode, icon and cover image upload, and other Yoto platform features used by the tool.
	- Common endpoints used in code: 
		- OAuth: `https://login.yotoplay.com/authorize` (browser sign-in) and `https://login.yotoplay.com/oauth/token` (code exchange and refresh)
		- Content and media: `https://api.yotoplay.com/content`, `https://api.yotoplay.com/media/transcode/audio/uploadUrl`, `https://api.yotoplay.com/media/upload/<id>/transcoded` and other `api.yotoplay.com` paths.

- YotoIcons (yotoicons.com)
	- Purpose: optional icon discovery / scraping when searching for suitable pixel art 16x16 icons.

- iTunes Search
	- Purpose: optional cover art search used by the `Add Cover Image` dialog to find album artwork by query.
	- Endpoint used: `https://itunes.apple.com/search` (no API key required for simple searches).

## Scopes and authorization flow

- Authorization code flow with PKCE (browser)
	- The device-code flow is deprecated by Yoto (see https://yoto.dev/authentication/device-code-migration/). The app instead opens the user's browser to sign in and catches the redirect on a temporary local loopback server.
	- The redirect URL must be registered for the (public) client in the Yoto developer dashboard; the default is `http://localhost:8550/oauth_callback`.
	- Scopes requested by default include `offline_access` (supplies a refresh token so the app can refresh tokens automatically) and `family:library:view` (read access to the family library).


## Privacy and data handling notes

- `tokens.json` contains OAuth access and refresh tokens — treat it as a secret. Do not commit it or publish it.
- Uploaded or cached media and icons may be stored locally under `.yoto_icon_cache`, `.yotoicons_cache`, and cache files such as `.yoto_api_cache.json`. These caches may contain URLs and metadata.

## References and links

- Yoto API base: https://api.yotoplay.com
- Yoto OAuth: https://login.yotoplay.com
- Yoto OAuth device-code migration: https://yoto.dev/authentication/device-code-migration/
- Yoto headless / CLI auth guide: https://yoto.dev/authentication/headless-cli-auth
- Yoto Developer dashboard: https://dashboard.yoto.dev/
- YotoIcons: https://www.yotoicons.com/
- iTunes Search API: https://itunes.apple.com/
