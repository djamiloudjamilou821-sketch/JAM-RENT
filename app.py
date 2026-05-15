from flask import Flask, render_template, request, redirect, session
import psycopg2
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
app = Flask(__name__)
import os
app.secret_key = os.urandom(24)

WEEKLY_FEE = 1000

ADMIN_PASSWORD = "1234"

DATABASE_URL ="postgresql://postgres.oceavsrrbcsgzwiwvjgl:D6zy46b+jQ?aMbg@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def check_admin_password(password):
    return password == ADMIN_PASSWORD
# ================= DATABASE INIT =================
def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # 👤 RENTERS TABLE (CLEAN VERSION)
    c.execute("""
        CREATE TABLE IF NOT EXISTS renters (
            id SERIAL PRIMARY KEY,
            name TEXT,
            phone TEXT,
            address TEXT,
            start_date TEXT,
            due_date TEXT,
            paid TEXT,
            last_payment_date TEXT
        )
    """)

    # 💳 PAYMENTS TABLE
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            renter_id INTEGER,
            amount INTEGER,
            payment_date TEXT
        )
    """)
    # PASSWORD
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT,
        password TEXT
    )
""")
    c.execute("SELECT * FROM users WHERE username=%s", ("admin",))
    if not c.fetchone():
        hashed = generate_password_hash("1234")
        c.execute("INSERT INTO users (username, password) VALUES (%s, %s)", ("admin", hashed))

    conn.commit()
    conn.close()

init_db()
#  
def get_week_range(today):
    weekday = today.weekday()

    # Wednesday = 2
    days_since_wed = (weekday - 2) % 7

    week_start = today - timedelta(days=days_since_wed)
    week_end = week_start + timedelta(days=6)

    return week_start, week_end
# ================= GLOBAL WEEK (WED → TUE) =================
def get_status(renter_id, start_date, today, cursor):

    week_start, week_end = get_week_range(today)

    # ⏳ due countdown based on REAL week
    days_left = (week_end - today).days
    if days_left < 0:
        days_left = 0

    due_info = f"Due in {days_left} days"

    # 💰 total paid
    cursor.execute("""
        SELECT SUM(amount) FROM payments
        WHERE renter_id=%s
    """, (renter_id,))

    total_paid = cursor.fetchone()[0] or 0

    # 🧮 weeks since start (aligned to Wednesday system)
    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    current_week_start, _ = get_week_range(today)
    start_week_start, _ = get_week_range(start_date)

    weeks_passed = ((current_week_start - start_week_start).days // 7) + 1

    if weeks_passed < 1:
        weeks_passed = 1

    expected = weeks_passed * WEEKLY_FEE
    debt = expected - total_paid

    if debt < 0:
        debt = 0

    return due_info, debt
# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect("/home")
        else:
            return "❌ Invalid credentials"

    return render_template("login.html")
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


# ================= ADD RENTER =================
@app.route("/add", methods=["GET", "POST"])
def add():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":

        name = request.form["name"]
        phone = request.form["phone"]
        address = request.form["address"]

        today = datetime.now().date()

        # 📅 weekly system start
        start_date = today
        due_date = today + timedelta(days=7)

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("""
            INSERT INTO renters (
                name,
                phone,
                address,
                start_date,
                due_date,
                paid,
                last_payment_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            name,
            phone,
            address,
            start_date.strftime("%Y-%m-%d"),
            due_date.strftime("%Y-%m-%d"),
            None,
            None
        ))

        conn.commit()
        conn.close()

        return redirect("/dashboard")

    return render_template("add.html")



@app.route("/")
def root():
    return redirect("/login")
# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    filter_type = request.args.get("filter")
    search = request.args.get("search", "")
    
    if search:
        c.execute("""
            SELECT * FROM renters
            WHERE name LIKE %s OR phone LIKE %s OR address LIKE %s
        """, (f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        c.execute("SELECT * FROM renters")

    renters = c.fetchall()

    today = datetime.now().date()

    updated = []
    paid_count = 0
    late_count = 0

    for r in renters:

        # ⏳ get due info + debt
        due_info, debt = get_status(r[0], r[4], today, c)

        # 🔥 force correct type
        debt = int(debt)

        # 📊 status (ONLY derived here)
        if debt > 0:
            status = "late"
            late_count += 1
        else:
            status = "paid"
            paid_count += 1

        # 🧱 build row
        row = r + (due_info, debt, status)

        updated.append(row)

    conn.close()

    # 🔥 FILTER SYSTEM
    if filter_type == "paid":
        updated = [r for r in updated if r[-1] == "paid"]

    elif filter_type == "overdue":
        updated = [r for r in updated if r[-1] == "late"]

    return render_template(
        "index.html",
        renters=updated,
        total=len(renters),
        paid=paid_count,
        overdue=late_count
    )
# ================= RENTERS PAGE =================
@app.route("/renters")
def renters():
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM renters")
    renters = c.fetchall()

    today = datetime.now().date()

    updated = []

    for r in renters:
        due_text, debt = get_status(r[0], r[4], today, c)

        updated.append(r + (due_text, debt))

    conn.close()

    return render_template("renters.html", renters=updated)
# ================= MONEY PAGE =================
@app.route("/money")
def money():
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM renters")
    renters = c.fetchall()

    today = datetime.now().date()

    paid = 0
    late = 0

    for r in renters:
        due_info, debt = get_status(r[0], r[4], today, c)

        if debt > 0:
            late += 1
        else:
            paid += 1

    c.execute("SELECT SUM(amount) FROM payments")
    collected = c.fetchone()[0] or 0

    expected = len(renters) * WEEKLY_FEE

    conn.close()

    return render_template(
        "money.html",
        total_renters=len(renters),
        paid_renters=paid,
        overdue_renters=late,
        weekly_fee=WEEKLY_FEE,
        collected_money=collected,
        expected_money=expected
    )

@app.route("/renter/<int:id>")
def renter_profile(id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    # =============================
    # 👤 GET RENTER
    # =============================
    c.execute("SELECT * FROM renters WHERE id=%s", (id,))
    renter = c.fetchone()

    if not renter:
        conn.close()
        return "Renter not found"

    # =============================
    # 💳 PAYMENT HISTORY
    # =============================
    c.execute("""
        SELECT amount, payment_date
        FROM payments
        WHERE renter_id=%s
        ORDER BY payment_date DESC
    """, (id,))
    payments = c.fetchall()

    # =============================
    # 📊 SUMMARY
    # =============================
    total_paid = sum(p[0] for p in payments) if payments else 0
    total_payments = len(payments)
    last_payment = payments[0][1] if payments else None

    # =============================
    # 🔥 CORE FIX (IMPORTANT)
    # =============================
    today = datetime.now().date()

    # ALWAYS calculate using SAME logic as dashboard
    due_info, debt = get_status(
        renter[0],   # renter_id
        renter[4],   # start_date
        today,
        c
    )

    conn.close()

    # =============================
    # 🎯 SEND TO TEMPLATE
    # =============================
    return render_template(
        "renter.html",
        renter=renter,
        payments=payments,
        total_paid=total_paid,
        total_payments=total_payments,
        last_payment=last_payment,
        due_info=due_info,
        debt=debt
    )

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_renter(id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM renters WHERE id=%s", (id,))
    renter = c.fetchone()

    if not renter:
        conn.close()
        return "Renter not found"

    if request.method == "POST":

        name = request.form.get("name")
        phone = request.form.get("phone")
        address = request.form.get("address")

        # 🔐 FIX: GET PASSWORD (YOU MISSED THIS)
        password = request.form.get("password", "").strip()

        # 🔐 CHECK USER PASSWORD
        c.execute("SELECT password FROM users WHERE username=%s", (session["user"],))
        data = c.fetchone()

        if not data or not check_password_hash(data[0], password):
            conn.close()
            return "❌ Wrong password"

        c.execute("""
            UPDATE renters
            SET name=%s, phone=%s, address=%s
            WHERE id=%s
        """, (name, phone, address, id))

        conn.commit()
        conn.close()

        return redirect("/renters")

    conn.close()
    return render_template("edit.html", renter=renter)
# DELETE
@app.route("/delete/<int:id>", methods=["GET", "POST"])
def delete(id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM renters WHERE id=%s", (id,))
    renter = c.fetchone()

    if not renter:
        conn.close()
        return "Renter not found"

    if request.method == "POST":

        password = request.form.get("password", "").strip()

        c.execute("SELECT password FROM users WHERE username=%s", (session["user"],))
        data = c.fetchone()

        if not data or not check_password_hash(data[0], password):
            conn.close()
            return "❌ Wrong password"

        c.execute("DELETE FROM payments WHERE renter_id=%s", (id,))
        c.execute("DELETE FROM renters WHERE id=%s", (id,))

        conn.commit()
        conn.close()

        return redirect("/renters")

    conn.close()
    return render_template("confirm_delete.html", renter=renter)

@app.route("/pay/<int:id>", methods=["GET", "POST"])
def pay(id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    # 👤 GET RENTER
    c.execute("SELECT * FROM renters WHERE id=%s", (id,))
    renter = c.fetchone()

    if not renter:
        conn.close()
        return "Renter not found"

    if request.method == "POST":

        password = request.form.get("password")

        # 🔐 OPTIONAL SECURITY (same system as pay/delete)
        c.execute("SELECT password FROM users WHERE username=%s", (session["user"],))
        data = c.fetchone()

        if not data or not check_password_hash(data[0], password):
            conn.close()
            return "❌ Wrong password"
    today = datetime.now().date()

    # 📅 CURRENT WEEK (WED → TUE)
    week_start, week_end = get_week_range(today)

    # 🔍 CHECK IF ALREADY PAID THIS WEEK
    c.execute("""
        SELECT * FROM payments
        WHERE renter_id=%s AND payment_date BETWEEN %s AND %s
    """, (
        id,
        week_start.strftime("%Y-%m-%d"),
        week_end.strftime("%Y-%m-%d")
    ))
    already_paid = c.fetchone()

    # 💰 CURRENT DEBT
    due_info, debt = get_status(renter[0], renter[4], today, c)

    # =============================
    # 💳 HANDLE PAYMENT
    # =============================
    

    # 💰 amount (optional input, default = WEEKLY_FEE)
    amount = request.form.get("amount")
    if amount:
        amount = int(amount)
    else:
        amount = WEEKLY_FEE

    # 🚫 Block only if NO debt AND already paid
    if debt == 0 and already_paid:
        conn.close()
        return  "⚠ Nothing to pay (already paid)"

    # 💳 SAVE PAYMENT
    c.execute("""
        INSERT INTO payments (renter_id, amount, payment_date)
        VALUES (%s, %s, %s)
    """, (
        id,
        amount,
        today.strftime("%Y-%m-%d")
    ))

    conn.commit()
    conn.close()

    return redirect("/renter/" + str(id))

    conn.close()

    # 📄 SHOW PAGE
    return render_template(
        "pay.html",
        renter=renter,
        debt=debt,
        due_info=due_info,
        already_paid=already_paid
    )
@app.route("/home")
def home():
    if "user" not in session:
        return redirect("/login")

    return render_template("home.html")

@app.route("/new-password", methods=["GET", "POST"])
def new_password():
    if "verify_user" not in session:
        return redirect("/verify-user")

    message = ""

    if request.method == "POST":
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            return "❌ New passwords do not match"

        conn = get_db_connection()
        c = conn.cursor()

        hashed = generate_password_hash(new_password)

        c.execute("""
            UPDATE users
            SET password=%s
            WHERE username=%s
        """, (hashed, session["verify_user"]))

        conn.commit()
        conn.close()

        session.pop("verify_user", None)

        return "✅ Password changed successfully"

    return render_template("new_password.html", message=message)

@app.route("/verify-user", methods=["GET", "POST"])
def verify_user():
    if "user" not in session:
        return redirect("/login")

    message = ""

    if request.method == "POST":
        password = request.form["password"]
        username = session["user"]

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE username=%s", (username,))
        data = c.fetchone()
        conn.close()

        if data and check_password_hash(data[0], password):
            # ✅ allow password change
            session["verify_user"] = username
            return redirect("/new-password")
        else:
            message = "❌ Incorrect password"

    return render_template("verify_user.html", message=message)
    
# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
