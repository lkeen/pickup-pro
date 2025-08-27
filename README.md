# 🏀 Pickup Pro

A **web app for organizing pickup basketball**.  
Find nearby courts, host games, join rosters (auto-capped), and track post-game stats and player ratings.

---

## 📌 Features

- **Court discovery** with lat/lng & radius search (Haversine)  
- **Host, join, and leave games**   
- **Session-based authentication**  
- **Post-game stats** (points / rebounds / assists) with per-user aggregates  
- **Player ratings & comments** 
- **Map UI** for courts (Leaflet.js)   

---

## 💻 Tech Stack

### **Frontend**
- **Templating:** Flask Jinja (server-rendered pages)  
- **Maps:** Leaflet.js   
- **Charts:** Chart.js 
- **Styling:** Vanilla CSS  
- **Client requests:** Fetch API  

### **Backend**
- **Framework:** Flask  
- **ORM:** SQLAlchemy (Flask-SQLAlchemy)  
- **Migrations:** Flask-Migrate (Alembic)  
- **Auth:** Flask-Login + Werkzeug password hashing    

### **Database**
- **Primary:** MySQL    

---

Future roadmap: add notifications, polish UI with Tailwind/Leaflet, and improve real-time updates.
