DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS availability;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    duration INTEGER NOT NULL,
    priority INTEGER CHECK(priority BETWEEN 1 AND 5),
    deadline DATETIME,
    category TEXT,
    is_completed BOOLEAN DEFAULT 0,
    scheduled_date TEXT, -- YYYY-MM-DD
    scheduled_time TEXT, -- HH:MM (24-hour format)
    is_manual_schedule BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    day_of_week TEXT,
    start_hour INTEGER,
    end_hour INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (id)
);