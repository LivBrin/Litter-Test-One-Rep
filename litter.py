import os
import json
from functools import wraps

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

server = Flask(__name__)

# Set SECRET_KEY as an environment variable on Render (any long random string).
server.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# Database.
# On Render, set FIREBASE_KEY_JSON to the full contents of your key file
# (or add litter_key.json as a Secret File). Locally it falls back to the file.
key_json = os.environ.get("FIREBASE_KEY_JSON")
if key_json:
    cred = credentials.Certificate(json.loads(key_json))
else:
    cred = credentials.Certificate("litter_key.json")
firebase_admin.initialize_app(cred)
database = firestore.client()


# must be logged in
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "You must be logged in"}), 401
        return f(*args, **kwargs)
    return wrapper


@server.route('/check')
def check():
    return "Firebase connected correctly", 200


# creates account: JSON body with "username" and "password"
@server.route('/create_account/', methods=['POST'])
def create_account():
    try:
        user_data = request.json or {}
        username = user_data.get('username')
        password = user_data.get('password')

        if not username or not password:
            return jsonify({"error": "You're missing a field!!"}), 400

        existing_user = database.collection("users").where("username", "==", username).get()
        if len(existing_user) > 0:
            return jsonify({"error": "This user already exists. Go sign in using the same credentials."}), 409

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        database.collection("users").add({
            "username": username,
            "password": hashed_password
        })

        return jsonify({"status": "success", "message": f"User {username} created"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# makes a post; JSON body needs "title" and "content"
@server.route('/create_post/', methods=["POST"])
@login_required
def create_post():
    username = session['username']
    try:
        users_ref = database.collection("users")
        results = users_ref.where('username', '==', username).limit(1).stream()

        user_doc = None
        for doc in results:
            user_doc = doc
            break

        if not user_doc:
            return jsonify({"error": "User not found"}), 404

        body = request.get_json()
        if not body or not body.get("content"):
            return jsonify({"error": "Post content is required"}), 400

        new_post = {
            "title": body.get("title"),
            "username": username,
            "content": body["content"],
            "likes": 0,
            "comments": [],
            "time_posted": firestore.SERVER_TIMESTAMP
        }

        new_post_db = database.collection("posts").add(new_post)
        post_id = new_post_db[1].id

        users_ref.document(user_doc.id).update({
            "posts": firestore.ArrayUnion([post_id])
        })

        return jsonify({"message": "post created successfully", "post_id": post_id}), 201

    except Exception as error:
        return jsonify({"error": str(error)}), 500


# delete a post. Route renamed to /delete/<id> to match the front end.
@server.route('/delete/<post_id>', methods=['DELETE'])
@login_required
def delete_post(post_id):
    try:
        post_ref = database.collection("posts").document(post_id)
        post_doc = post_ref.get()
        if not post_doc.exists:
            return jsonify({"error": "No post found"}), 404

        # only the author can delete their own post
        if post_doc.to_dict().get("username") != session['username']:
            return jsonify({"error": "You can only delete your own posts"}), 403

        post_ref.delete()

        # also remove the id from the user's list of posts
        users = database.collection("users").where("username", "==", session['username']).limit(1).get()
        if len(users) > 0:
            users[0].reference.update({"posts": firestore.ArrayRemove([post_id])})

        return jsonify({"status": "success", "message": "Post deleted", "firebase_id": post_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# add comment to post: post id in URL, comment JSON in body
@server.route('/add_comment/<post_id>', methods=['PUT'])
@login_required
def add_comment(post_id):
    try:
        comment_data = request.json
        if not comment_data:
            return jsonify({"error": "no data provided"}), 400

        post_ref = database.collection("posts").document(post_id)
        post_doc = post_ref.get()
        if not post_doc.exists:
            return jsonify({"error": "no post found with that id"}), 404

        comments = post_doc.to_dict().get("comments", [])
        comments.append(comment_data)
        post_ref.update({"comments": comments})

        return jsonify({"status": "success", "message": "Comment added", "firebase_id": post_doc.id}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# like a post, must have post id
@server.route('/like/<post_id>', methods=['PUT'])
def like(post_id):
    try:
        post_ref = database.collection("posts").document(post_id)
        if not post_ref.get().exists:
            return jsonify({"error": "No post found with that id"}), 404

        # atomic increment so two simultaneous likes aren't lost
        post_ref.update({"likes": firestore.Increment(1)})

        return jsonify({"status": "Success", "message": "Post liked", "firebase_id": post_id}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@server.route('/my-posts/', methods=['GET'])
@login_required
def my_posts():
    try:
        username = session['username']
        user_query = database.collection("users").where("username", "==", username).limit(1).get()

        if len(user_query) == 0:
            return jsonify({"error": "User not found"}), 404

        post_ids = user_query[0].to_dict().get("posts", [])

        posts = []
        for post_id in post_ids:
            post_doc = database.collection("posts").document(post_id).get()
            if post_doc.exists:
                post_data = post_doc.to_dict()
                post_data['id'] = post_doc.id
                posts.append(post_data)

        return jsonify(posts), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@server.route('/login/', methods=['POST'])
def login():
    try:
        data = request.json or {}
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        results = database.collection("users").where("username", "==", username).limit(1).get()

        # Same message for "no user" and "wrong password"
        if len(results) == 0:
            return jsonify({"error": "Invalid username or password"}), 401

        user = results[0].to_dict()
        if not check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid username or password"}), 401

        session['username'] = username
        return jsonify({"status": "success", "message": f"Welcome back, {username}"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@server.route('/logout/', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "success", "message": "Logged out"}), 200


# serve the front end
@server.route('/')
def home():
    return send_from_directory('static', 'index.html')


@server.route('/posts/', methods=['GET'])
def get_posts():
    try:
        docs = (database.collection("posts")
                .order_by("time_posted", direction=firestore.Query.DESCENDING)
                .limit(50).stream())
        posts = []
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id
            posts.append(p)
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@server.route('/me')
def me():
    return jsonify({"username": session.get('username')})


# Run server locally (Render uses gunicorn instead)
if __name__ == "__main__":
    server.run(debug=True, port=5000)
