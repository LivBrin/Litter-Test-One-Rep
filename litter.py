
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash

server = Flask(__name__)
server.secret_key = 'your_secret_key_here'  # Replace with a real secret key

# Database
cred = credentials.Certificate("litter_key.json")
firebase_admin.initialize_app(cred)
database = firestore.client()

#auth routes


from functools import wraps

#must log in
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "You must be logged in"}), 401
        return f(*args, **kwargs)
    return wrapper

#only run if server isn't working to check condition of running-ness
@server.route('/check')
def check():
    return "Firebase connected correctly", 200


#creates account, add "username":"", and "password":"" in raw json to create
@server.route('/create_account/', methods=['POST'])
def create_account():
    try:
        user_data = request.json
        username = user_data.get('username')
        password = user_data.get('password')

        if not username or not password:
            return jsonify({"error": "You're missing a field!!"})
        
        existing_user = database.collection("users").where("username", "==", username).get()

        if len(existing_user) > 0 :
            return jsonify({"error":"This user already exists. Go sign in using the same credentials."})
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        new_entry = {
            "username": username,
            "password": hashed_password
        }
        
        database.collection("users").add(new_entry)

        return jsonify({"status":"success","message":f"User {username} created"}), 201
    
    except Exception as e:
        return jsonify({"error": str(e)},500)


# Routes


# NOTES ON METHODS
# GET --> used to get/read/access information from the database
# POST --> used to post/create new info to our database
# PUT --> used to edit info from our database

#typically not used but can retrieve list of all attributes of all users, unnecessary for this type of application
# @server.route('/all_users/', methods=['GET'])
# def all_users():
#     try:
#         users_ref = database.collection("users")
#         docs = users_ref.stream()
        
#         users_list = []
#         for doc in docs:
#             user_data = doc.to_dict()
#             user_data['id'] = doc.id
#             users_list.append(user_data)

#         return jsonify(users_list), 200


#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
        
    
#makes a post, must include  title and content, nothing else dw
@server.route('/create_post/', methods=["POST"])
def create_post():
    username = session['username']
    try:
        users_ref = database.collection("users")
        query = users_ref.where('username','==', username).limit(1)
        results = query.stream()

        user_data = None
        for doc in results:
            user_data = doc.to_dict()
            user_data['id'] = doc.id
            break

        if not user_data:
            raise Exception("User not found")
        
        body = request.get_json()
        if not body:
            raise Exception("empty body?")
        
        new_post = {
            "title": body.get("title"),
            "username": username,
            "content": body["content"],
            "likes": 0,
            "comments": [],
            "time_posted": firestore.SERVER_TIMESTAMP
        }
        
        post_collection = database.collection("posts")
        new_post_db = post_collection.add(new_post)
        post_id = new_post_db[1].id

        users_ref.document(user_data['id']).update({
        "posts": firestore.ArrayUnion([post_id])
})

        return jsonify({
            "message":"post created successfully",
            "post_id": post_id
        })

    except Exception as error:
        return jsonify({"error":str(error)})


  #must aquire post id but otherwise no input  



#delete a post -- needs post id but no other input
@server.route('/delete_post/<post_id>', methods=['DELETE'])
@login_required
def delete_post(post_id):
    try:
        post_ref = database.collection("posts").document(post_id)#finding doc by id
        if not post_ref.get().exists:
            return jsonify({"no post found"}), 404
        else:
            post_ref.delete()
            return jsonify({
                "status": "success",
                "message": "Post deleted",
                "firebase_id": post_id
            }, 201)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


#add comment to post, all needed is post id and content in raw json body 
@server.route('/add_comment/<post_id>', methods=['PUT'])
def add_comment(post_id):
    try:
        comment_data = request.json
        if not comment_data:
            return jsonify("error: no data provided"), 400

        post_ref = database.collection("posts").document(post_id)
        post_doc = post_ref.get()
        if not post_doc.exists:
            return jsonify("error: no post found with that id"), 404

        if not post_doc:
            return jsonify("error: no post found with that title"), 404

        comments = post_doc.to_dict().get("comments", [])
        comments.append(comment_data)

        post_ref = database.collection("posts").document(post_doc.id)
        post_ref.update({"comments": comments})

        return jsonify({
            "status": "success",
            "message": "Comment added",
            "firebase_id": post_doc.id
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
 

#like a post, must have post id
@server.route('/like/<post_id>', methods=['PUT'])
def like(post_id):
    try:
        post_ref = database.collection("posts").document(post_id)
        post_doc = post_ref.get()
        if not post_doc.exists:
            return jsonify("Error: No post found with that id"), 404

        if not post_doc:
            return jsonify("Error: No post found with that title"), 404

        likes = post_doc.to_dict().get("likes", int(0))
        likes += 1

        post_ref = database.collection("posts").document(post_doc.id)
        post_ref.update({"likes": likes})

        return jsonify({
            "status": "Success",
            "message": "Post liked",
            "firebase_id": post_doc.id
        }), 200

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

        user_doc = user_query[0]
        user_data = user_doc.to_dict()
        post_ids = user_data.get("posts", [])

        posts = []
        for post_id in post_ids:
            post_ref = database.collection("posts").document(post_id)
            post_doc = post_ref.get()
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

        # Same message for "no user" and "wrong password" so attackers can't tell which was wrong
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

# @server.route('/add_project')



from flask import send_from_directory   # add to your imports
# connect to html
@server.route('/')
def home():
    return send_from_directory('static', 'index.html')

@server.route('/posts/', methods=['GET'])
def get_posts():
    docs = (database.collection("posts")
            .order_by("time_posted", direction=firestore.Query.DESCENDING)
            .limit(50).stream())
    posts = []
    for doc in docs:
        p = doc.to_dict()
        p['id'] = doc.id
        posts.append(p)
    return jsonify(posts)



@server.route('/me')
def me():
    return jsonify({"username": session.get('username')})



# Run server
if __name__ == "__main__":
    server.run(debug=True, port=5000)

    #DATABASE

    #Collection is library
    #title - str
    #author - str
    #genre - str
    #year published - int
    #language - str
    #pages - int

#GET - '/all' -> gives all books in library
#POST - new info
#DELETE - delete info
#GET - 'search/<book_name> - find book
