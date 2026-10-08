# Contributing

Use Python 3.11 or newer. Create a virtual environment and install
`requirements.txt`, then follow the README to start a local game.

Before submitting a change:

```sh
python tools/check_release.py
python -m pip check
python -m unittest discover -s tests -v
node --check static/client.js
node --check static/legacy-client.js
```

Node.js is needed only for the JavaScript syntax checks. Game tests use disposable
SQLite databases and disable the scheduler; never use a real player save as a test
fixture. For manual testing, set DB_PATH to a separate file and use a test account.

Keep spending and permissions checked on the server. Describe and test any save
migration, ensure it is idempotent, and preserve existing ownership and balances.
Centralize balance values in config.py. Test touch controls, mobile notifications,
menu scrolling, coastline/landings and keyboard navigation when changing the UI.
Update README and CHANGELOG for player/host-facing changes; update VERSION when
shipping an update. Do not commit private saves, IP logs, session keys, music,
recovery codes, feedback files or copyrighted artwork.

Open an issue to discuss a substantial change. Include the problem, resulting
behavior and meaningful validation in pull requests. See SECURITY.md for security
issues. The project owner chooses the repository's licence before accepting
contributions under an open-source licence.
