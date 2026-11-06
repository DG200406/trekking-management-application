# Trekking Management Application

Flask + SQLite + Jinja2/Bootstrap trekking management system with three roles: Admin, Trek Staff, and Trekker (User).

## Setup

```
pip install -r requirements.txt
python seed_db.py      # creates trekking.db and fills it with demo data
python app.py           # runs at http://127.0.0.1:5000
```

Re-run `python seed_db.py` any time to reset the database to a clean demo state.

## Demo Logins

| Role    | Email                | Password  | Notes              |
|---------|-----------------------|-----------|---------------------|
| Admin   | admin@trek.com        | admin123  | pre-seeded superuser |
| Staff   | ravi@trek.com         | staff123  | approved            |
| Staff   | meena@trek.com        | staff123  | approved            |
| Staff   | karan@trek.com        | staff123  | pending approval    |
| Staff   | suresh@trek.com       | staff123  | blacklisted         |
| Trekker | aditi@example.com     | user123   | active              |
| Trekker | rohan@example.com     | user123   | active              |
| Trekker | sneha@example.com     | user123   | active              |
| Trekker | vikram@example.com    | user123   | blacklisted         |
