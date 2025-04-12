from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
from flask_socketio import SocketIO, emit, join_room
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret_key"
app.config["MONGO_URI"] = "mongodb://localhost:27017/chatapp"
mongo = PyMongo(app)
socketio = SocketIO(app)

connected_users = {}  # sid -> username
user_rooms = {}       # username -> room_id

# Dummy friends for now (can be replaced with real friend system)
def get_friends(username):
    all_users = mongo.db.users.find({}, {"_id": 0, "username": 1})
    return [u['username'] for u in all_users if u['username'] != username]

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if mongo.db.users.find_one({"username": username}):
            flash("Username already exists!")
            return redirect(url_for('register'))

        hashed = generate_password_hash(password)
        mongo.db.users.insert_one({"username": username, "password": hashed})
        return redirect(url_for('login'))
    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = mongo.db.users.find_one({"username": username})
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('chat'))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    users = get_friends(session['username'])
    return render_template("chat.html", current_user=session['username'], friends=users)

@app.route('/search_user')
def search_user():
    query = request.args.get("query", "")
    user = mongo.db.users.find_one({"username": {"$regex": f"^{query}$", "$options": "i"}})
    if user:
        return redirect(url_for('chat_with_user', username=user['username']))
    flash("User not found.")
    return redirect(url_for('chat'))

@app.route('/chat/<username>')
def chat_with_user(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    current_user = session['username']
    friends = get_friends(current_user)

    # Fetch previous messages
    messages = list(mongo.db.messages.find({
        "$or": [
            {"sender": current_user, "receiver": username},
            {"sender": username, "receiver": current_user}
        ]
    }).sort("timestamp", 1))

    return render_template('chat.html', current_user=current_user, current_chat=username, friends=friends, messages=messages)

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        connected_users[request.sid] = session['username']
        user_rooms[session['username']] = request.sid

@socketio.on('disconnect')
def handle_disconnect():
    username = connected_users.pop(request.sid, None)
    if username:
        user_rooms.pop(username, None)

@socketio.on("private_message")
def handle_private_message(data):
    sender = session['username']
    receiver = data['receiver']
    message = data['message']
    timestamp = datetime.utcnow()

    # Save message to MongoDB
    mongo.db.messages.insert_one({
        "sender": sender,
        "receiver": receiver,
        "message": message,
        "timestamp": timestamp
    })

    # Send message to receiver if connected
    room = user_rooms.get(receiver)
    if room:
        emit("new_private_message", {
            "sender": sender,
            "message": message,
            "timestamp": timestamp.isoformat()
        }, room=room)

    # Also send to sender for confirmation
    emit("new_private_message", {
        "sender": sender,
        "message": message,
        "timestamp": timestamp.isoformat()
    }, room=request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True)
