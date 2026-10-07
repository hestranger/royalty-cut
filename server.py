from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from zoneinfo import ZoneInfo
import json, os, secrets, sqlite3

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, 'royalty_cut.db')
ADMIN_PASSWORD = os.environ.get('ROYALTY_ADMIN_PASSWORD', 'change-this-password')
PORT = int(os.environ.get('PORT', '8000'))
TIMEZONE = ZoneInfo('Africa/Lagos')
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

# Optional PostgreSQL support for production. Local development uses SQLite automatically.
PG = None
if DATABASE_URL:
    try:
        import psycopg
        from psycopg.rows import dict_row
        PG = psycopg
    except ImportError as exc:
        raise SystemExit('DATABASE_URL is set but psycopg is not installed. Run: pip install -r requirements.txt') from exc

SESSIONS = set()


def db():
    if PG:
        return PG.connect(DATABASE_URL, row_factory=dict_row)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def execute(c, sql, params=()):
    # Keep one SQL dialect in the application by translating placeholders for PostgreSQL.
    if PG:
        sql = sql.replace('?', '%s')
    return c.execute(sql, params)


def init_db():
    c = db()
    if PG:
        execute(c, '''CREATE TABLE IF NOT EXISTS bookings (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            location TEXT NOT NULL,
            note TEXT,
            price TEXT,
            payment_status TEXT NOT NULL DEFAULT 'awaiting_payment',
            appointment_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )''')
        execute(c, '''CREATE INDEX IF NOT EXISTS idx_bookings_date_time ON bookings(date, time)''')
    else:
        execute(c, '''CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            location TEXT NOT NULL,
            note TEXT,
            price TEXT,
            payment_status TEXT NOT NULL DEFAULT 'awaiting_payment',
            appointment_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )''')
        execute(c, 'CREATE INDEX IF NOT EXISTS idx_bookings_date_time ON bookings(date, time)')
    c.commit()
    c.close()


init_db()


def send_json(h, code, data):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    h.send_response(code)
    h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Content-Length', str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)


def clean(value, max_len=500):
    return str(value or '').strip()[:max_len]


def valid_date_time(date_s, time_s):
    try:
        dt = datetime.strptime(f'{date_s} {time_s}', '%Y-%m-%d %H:%M').replace(tzinfo=TIMEZONE)
        return dt >= datetime.now(TIMEZONE)
    except ValueError:
        return False


def price_for(service):
    return {
        'Haircut & Styling — $10': '$10',
        'Beard Trimming & Grooming — $7': '$7',
        'Hair Treatment — $5': '$5',
        'Special Service — Doorstep': 'Contact for price',
    }.get(service, 'Contact for price')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def _body(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n > 100_000:
                raise ValueError('Request too large')
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return None

    def do_POST(self):
        p = urlparse(self.path).path

        if p == '/api/bookings':
            d = self._body()
            if not isinstance(d, dict):
                return send_json(self, 400, {'error': 'Invalid request.'})
            required = ['name', 'phone', 'service', 'date', 'time', 'location']
            if any(not clean(d.get(k)) for k in required):
                return send_json(self, 400, {'error': 'Please complete all required booking details.'})
            data = {k: clean(d.get(k), 250) for k in required}
            data['note'] = clean(d.get('note'), 1000)
            if not valid_date_time(data['date'], data['time']):
                return send_json(self, 400, {'error': 'Please choose a valid future date and time.'})

            c = db()
            try:
                exists = execute(c, "SELECT id FROM bookings WHERE date=? AND time=? AND appointment_status NOT IN ('cancelled','completed') LIMIT 1", (data['date'], data['time'])).fetchone()
                if exists:
                    return send_json(self, 409, {'error': 'That time is already booked. Please choose another time.'})
                cur = execute(c, '''INSERT INTO bookings(name,phone,service,date,time,location,note,price,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?) RETURNING id''',
                    (data['name'], data['phone'], data['service'], data['date'], data['time'], data['location'], data['note'], price_for(data['service']), datetime.now(TIMEZONE).isoformat()))
                row = cur.fetchone()
                c.commit()
                bid = row['id'] if isinstance(row, dict) else row[0]
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()
            return send_json(self, 201, {'id': int(bid), 'booking_id': f'RC-{int(bid):05d}', 'status': 'pending'})

        if p == '/api/admin/login':
            d = self._body() or {}
            password = str(d.get('password', ''))
            if ADMIN_PASSWORD == 'change-this-password':
                return send_json(self, 503, {'error': 'Admin password is not configured. Set ROYALTY_ADMIN_PASSWORD before starting the server.'})
            if secrets.compare_digest(password, ADMIN_PASSWORD):
                token = secrets.token_urlsafe(32)
                SESSIONS.add(token)
                return send_json(self, 200, {'token': token})
            return send_json(self, 401, {'error': 'Invalid password.'})

        if p == '/api/admin/logout':
            SESSIONS.discard(self.headers.get('X-Admin-Token', ''))
            return send_json(self, 200, {'ok': True})

        return send_json(self, 404, {'error': 'Not found'})

    def do_GET(self):
        p = urlparse(self.path).path

        if p == '/api/health':
            return send_json(self, 200, {'ok': True, 'database': 'postgresql' if PG else 'sqlite'})

        if p == '/api/availability':
            date_s = (parse_qs(urlparse(self.path).query).get('date') or [''])[0]
            c = db()
            rows = execute(c, "SELECT time FROM bookings WHERE date=? AND appointment_status NOT IN ('cancelled','completed') ORDER BY time", (date_s,)).fetchall()
            c.close()
            return send_json(self, 200, {'booked': [r['time'] if isinstance(r, dict) else r[0] for r in rows]})

        if p == '/api/admin/bookings':
            if self.headers.get('X-Admin-Token') not in SESSIONS:
                return send_json(self, 401, {'error': 'Unauthorized'})
            c = db()
            rows = execute(c, 'SELECT * FROM bookings ORDER BY date,time,id').fetchall()
            c.close()
            return send_json(self, 200, {'bookings': [dict(r) for r in rows]})

        return super().do_GET()

    def do_PATCH(self):
        p = urlparse(self.path).path
        if not p.startswith('/api/admin/bookings/') or self.headers.get('X-Admin-Token') not in SESSIONS:
            return send_json(self, 401, {'error': 'Unauthorized'})
        bid = p.rsplit('/', 1)[-1]
        if not bid.isdigit():
            return send_json(self, 400, {'error': 'Invalid booking ID.'})
        d = self._body() or {}
        allowed = {'payment_status': {'awaiting_payment', 'paid', 'refunded'}, 'appointment_status': {'pending', 'confirmed', 'cancelled', 'completed'}}
        updates, vals = [], []
        for k, allowed_values in allowed.items():
            if k in d:
                v = clean(d[k], 40)
                if v not in allowed_values:
                    return send_json(self, 400, {'error': f'Invalid {k}.'})
                updates.append(k + '=?'); vals.append(v)
        if not updates:
            return send_json(self, 400, {'error': 'No valid changes.'})
        vals.append(int(bid))
        c = db()
        execute(c, 'UPDATE bookings SET ' + ','.join(updates) + ' WHERE id=?', vals)
        c.commit(); c.close()
        return send_json(self, 200, {'ok': True})


if __name__ == '__main__':
    print(f'ROYALTY CUT server running on port {PORT}')
    print(f'Database: {"PostgreSQL" if PG else "SQLite"}')
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
