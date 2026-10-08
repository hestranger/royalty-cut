# ROYALTY CUT — Cloudflare deployment

This version uses Cloudflare Workers + D1. The customer website is in `public/`; `worker.js` provides the booking API and admin API.

## Cloudflare setup
1. Create a D1 database named `royalty-cut-db`.
2. In the Worker settings, add a D1 binding named `DB` pointing to that database.
3. Run the SQL in `schema.sql` against the D1 database.
4. Add Worker secrets/variables:
   - `ADMIN_PASSWORD` = your private admin password
   - `ADMIN_SECRET` = a long random secret
5. Deploy with `npx wrangler deploy`.

Do not use the old Python `server.py` with Cloudflare Workers.
