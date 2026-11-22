# Customer portal

A small web page for a parcel's recipient: sign in with a mobile number, see
your parcels in one organization and open the locker door with a pickup code.
Plain HTML, CSS and JavaScript modules; nothing to build or install.

Run it next to the API (the API must allow this origin, see `CORS_ALLOWED_ORIGINS`
in `.env.example`):

    CORS_ALLOWED_ORIGINS=http://127.0.0.1:8080 uv run python manage.py runserver 8010
    python3 -m http.server 8080 --bind 127.0.0.1 --directory frontend

Then open `http://127.0.0.1:8080/?org=<organization slug>`. In development the
sign-in code is printed in the API's log. The API address is `API_BASE` in
`js/config.js`.

The access token is kept in memory and the refresh token in `sessionStorage`.
Every pickup request carries an `Idempotency-Key`, so a retry after a dropped
connection never opens the door twice. Fonts are self-hosted (OFL, see `fonts/`).

## Staff panel

`staff/` is for an organization's members: list parcels (filter by status), create
one, put it into a locker and text its pickup code. It signs in the same way, with a
phone number, and uses the same API; what a member may do is still decided by the
server. Open `http://127.0.0.1:8080/staff/?org=<organization slug>`. A number that is
not a member of the organization is told so; admins add members through the API
(`POST members/`), there is no screen for that yet.
