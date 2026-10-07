ROYALTY CUT — BOOKING ENGINE

This project converts the static ROYALTY CUT site into a small working booking application.

FILES
- index.html: customer-facing website
- admin.html: private appointment dashboard
- server.py: backend API + SQLite database
- royalty_cut.db: created automatically on first run

RUN LOCALLY
1. Install Python 3.
2. In this folder run:
   ROYALTY_ADMIN_PASSWORD="choose-a-strong-password" python3 server.py
3. Open http://localhost:8000/
4. Open http://localhost:8000/admin.html for Royalty's dashboard.

WHAT WORKS
- Saves bookings into SQLite.
- Prevents two active bookings from taking the exact same date/time.
- Creates a Booking ID.
- Opens WhatsApp with the saved booking details pre-filled.
- Admin login.
- Admin can view bookings and mark payment/appointment status.

BEFORE PUBLIC LAUNCH
- Use a real production database/managed server rather than local SQLite if multiple servers are used.
- Use HTTPS.
- Change the admin password and store it as a server secret.
- Add stronger authentication/rate limiting/CSRF protections as appropriate.
- Deploy the backend and frontend under the same production domain or configure CORS carefully.
- If online payments are added later, connect a provider such as Paystack/Flutterwave on the server side; never expose secret API keys in HTML.
