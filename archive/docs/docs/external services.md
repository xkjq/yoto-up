## External services used by Yoto-UP

This document lists third-party hosts and services the project uses or may contact at runtime, why they are used, and the relevant endpoints.

### Quick inventory

- Yoto API (primary service): https://api.yotoplay.com
- Yoto OAuth / Device authorization: https://login.yotoplay.com (device code and token endpoints)
- YotoIcons (icon discovery / scraping): https://www.yotoicons.com
- iTunes Search API (cover art lookup): https://itunes.apple.com/search
- NLTK data downloads (punkt, stopwords) — external NLTK servers
- Asciinema embeds used in the docs: https://asciinema.org
- GitHub (repo and releases): https://github.com/xkjq/yoto-up

## Purpose and main endpoints

- Yoto API (api.yotoplay.com)
	- Purpose: content management (get/create/update/delete cards), media upload/transcode, icon and cover image upload, and other Yoto platform features used by the tool.
	- Common endpoints used in code: 
		- Device / OAuth: `https://login.yotoplay.com/oauth/device/code` and `https://login.yotoplay.com/oauth/token`
		- Content and media: `https://api.yotoplay.com/content`, `https://api.yotoplay.com/media/transcode/audio/uploadUrl`, `https://api.yotoplay.com/media/upload/<id>/transcoded` and other `api.yotoplay.com` paths.

- YotoIcons (yotoicons.com)
	- Purpose: optional icon discovery / scraping when searching for suitable pixel art 16x16 icons.

- iTunes Search
	- Purpose: optional cover art search used by the `Add Cover Image` dialog to find album artwork by query.
	- Endpoint used: `https://itunes.apple.com/search` (no API key required for simple searches).

## Scopes and device flow

- Device authorization flow
	- The project uses OAuth device flow. The app requests a device code, prints a verification URL and code, and polls for the token.
	- Scopes requested by default include `profile` and `offline_access` (offline_access supplies a refresh token so the app can refresh tokens automatically).


## Privacy and data handling notes

- `tokens.json` contains OAuth access and refresh tokens — treat it as a secret. Do not commit it or publish it.
- Uploaded or cached media and icons may be stored locally under `.yoto_icon_cache`, `.yotoicons_cache`, and cache files such as `.yoto_api_cache.json`. These caches may contain URLs and metadata.

## References and links

- Yoto API base: https://api.yotoplay.com
- Yoto OAuth / Device: https://login.yotoplay.com
- Yoto Developer dashboard: https://dashboard.yoto.dev/
- YotoIcons: https://www.yotoicons.com/
- iTunes Search API: https://itunes.apple.com/
