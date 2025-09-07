# Security

Important notes before publishing or sharing this repository:

- Do NOT commit `tokens.json` or any files containing access/refresh tokens. `tokens.json` is listed in `.gitignore` by default, but you should still remove local token files before publishing.
- The application client ID is currently stored in `yoto_app/config.py`. If you are forking or adapting the code, please generate your own at the [Yoto Developer dashboard](https://dashboard.yoto.dev/). 