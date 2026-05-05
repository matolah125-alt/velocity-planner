import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from helpers import get_optimized_plan, get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-mode-key-change-this-in-prod")

@app.template_filter('format_duration')
def format_duration(hours):
    try:
        total_minutes = int(round(float(hours) * 60))
        if total_minutes == 0:
            return "0 mins"
        h = total_minutes // 60
        m = total_minutes % 60
        if h > 0 and m > 0:
            return f"{h} hr{'s' if h > 1 else ''} {m} min{'s' if m > 1 else ''}"
        elif h > 0:
            return f"{h} hr{'s' if h > 1 else ''}"
        else:
            return f"{m} min{'s' if m > 1 else ''}"
    except (ValueError, TypeError):
        return hours

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    # Onboarding: Redirect to add task if the user has no pending tasks
    db = get_db_connection()
    task_count = db.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND is_completed = 0', (session["user_id"],)).fetchone()[0]
    db.close()
    if task_count == 0:
        return redirect(url_for('add_task'))

    organized_diary = get_optimized_plan(session["user_id"], 24)
    return render_template('index.html', tasks=organized_diary)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Username and password are required", "error")
            return redirect(url_for('register'))

        db = get_db_connection()
        try:
            db.execute('INSERT INTO users (username, hash) VALUES (?, ?)', 
                       (username, generate_password_hash(password)))
            db.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already exists", "error")
            return redirect(url_for('register'))
        except sqlite3.OperationalError as e:
            flash(f"Database error: {e}. Did you run init_db.py?", "error")
            return redirect(url_for('register'))
        finally:
            db.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    session.clear()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = get_db_connection()
        try:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user and check_password_hash(user['hash'], password):
                session['user_id'] = user['id']
                return redirect(url_for('index'))
        except sqlite3.OperationalError as e:
            flash(f"Database error: {e}", "error")
            return redirect(url_for('login'))
        finally:
            db.close()
            
        flash("Invalid username or password", "error")
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_task():
    if request.method == 'POST':
        title = request.form.get('title')
        try:
            duration = int(request.form.get('duration', 0))
            priority = int(request.form.get('priority', 1))
            scheduled_date = request.form.get('scheduled_date')
            scheduled_time = request.form.get('scheduled_time')
        except (ValueError, TypeError):
            # Return a simple error or flash a message if the inputs aren't numbers
            return "Invalid input for duration or priority", 400

        is_manual_schedule = 1 if scheduled_date and scheduled_time else 0

        db = get_db_connection()
        db.execute('INSERT INTO tasks (user_id, title, duration, priority, scheduled_date, scheduled_time, is_manual_schedule) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (session["user_id"], title, duration, priority, scheduled_date, scheduled_time, is_manual_schedule))
        db.commit()
        db.close()
        return redirect(url_for('index'))

    return render_template('add.html')

@app.route('/complete_task', methods=['POST'])
@login_required
def complete_task():
    task_id = request.form.get('task_id')
    if task_id:
        try:
            task_id = int(task_id)
            db = get_db_connection()
            # Ensure the task belongs to the logged-in user before marking as complete
            db.execute('UPDATE tasks SET is_completed = 1 WHERE id = ? AND user_id = ?',
                       (task_id, session["user_id"]))
            db.commit()
            db.close()
        except (ValueError, TypeError):
            return "Invalid task ID", 400 # Or flash a message
    return redirect(url_for('index'))

@app.route('/push/<int:task_id>', methods=['GET', 'POST'])
@login_required
def push_task(task_id):
    db = get_db_connection()
    task = db.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, session["user_id"])).fetchone()
    
    if not task:
        db.close()
        return "Task not found", 404
        
    if request.method == 'POST':
        scheduled_date = request.form.get('scheduled_date')
        scheduled_time = request.form.get('scheduled_time')
        
        is_manual = 1 if scheduled_date and scheduled_time else 0
        
        db.execute('UPDATE tasks SET scheduled_date = ?, scheduled_time = ?, is_manual_schedule = ? WHERE id = ?',
                   (scheduled_date, scheduled_time, is_manual, task_id))
        db.commit()
        db.close()
        return redirect(url_for('index'))
        
    db.close()
    return render_template('push.html', task=task)

if __name__ == "__main__":
    app.run(debug=True)