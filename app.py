import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, abort, render_template
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from bson.objectid import InvalidId
from apscheduler.schedulers.background import BackgroundScheduler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()


# This is the object model to be uploaded to the MongoDb database
class Quiz:
    def __init__(self, question, options, right_answer, start_date, end_date):
        self.id = None
        self.question = question
        self.options = options
        self.right_answer = right_answer
        self.start_date = start_date
        self.end_date = end_date
        self.status = False


# Flask app is created
app = Flask(__name__)

# Limiter to limit the requests from a single IP address
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["1000 per day"],
    storage_uri="memory://",
)

# MongoDb configuration
mongo_client = MongoClient(os.environ.get("MONGODB_CONNECTION_URL"))
db = mongo_client["timed_quiz"]
quizzes_collection = db["quizzes"]

# Background task that updates the Status of the Quiz -- Active or Not
scheduler = BackgroundScheduler()
scheduler.start()


# Function to change the status of the quiz
def update_quiz_status():
    now = datetime.now()

    # Status of quiz that has Started
    quizzes_collection.update_many(
        {"start_date": {"$lte": now}}, {"$set": {"status": True}}
    )

    # Status of quiz that has ended
    quizzes_collection.update_many(
        {"end_date": {"$lte": now}}, {"$set": {"status": False}}
    )


# Status Updater -- runs every 5 minutes
scheduler.add_job(update_quiz_status, "interval", minutes=5)


# Api home page -- documentation
@app.route("/")
def home():
    return render_template("index.html")


# 1. POST /quizzes - to create a new quiz -- can accept data in form of JSON or x-www-form-urlencoded  -- limit of 10 per minute
# It return the ID if successefully created
@app.route("/quizzes", methods=["POST"])
@limiter.limit("10 per minute")
def create_quiz():
    if request.headers["Content-Type"] == "application/json":  # JSON data
        json_data = request.get_json()
        data = request.get_json()

        if data is None:
            abort(400, "Invalid request body. JSON data expected.")

        question = data.get("question")
        options_raw = data.get("options")
        options = [option.strip() for option in options_raw.split(",")]
        right_answer = int(data.get("rightAnswer"))
        start_date = datetime.fromisoformat(data.get("startDate"))
        end_date = datetime.fromisoformat(data.get("endDate"))

    elif (
        request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    ):  # Form data
        form_data = request.form
        question = request.form.get("question")
        entered_right_answer = request.form.get("rightAnswer")
        entered_options_data = str(request.form.get("options"))
        entered_start_date = request.form.get("startDate")
        entered_end_date = request.form.get("endDate")

        if (
            entered_right_answer == ""
            or entered_start_date == ""
            or entered_end_date == ""
            or entered_options_data is None
            and data is None
        ):
            abort(400, "Invalid request body. Missing Data.")

        options = [option.strip() for option in entered_options_data.split(",")]
        right_answer = int(entered_right_answer)
        start_date = datetime.fromisoformat(entered_start_date)
        end_date = datetime.fromisoformat(entered_end_date)

    else:
        abort(400, "Unsupported Media Type or empty body")

    if right_answer < 1 or right_answer > len(options):
        abort(400, "Invalid rightAnswer index")

    if start_date >= end_date:
        abort(400, "End date must be a date after the start date")

    # now = datetime.now()
    # print(now, start_date, end_date)
    # if start_date < now or end_date < now:
    #     abort(400, 'Start date and end date must be a future date (Tomorrow)')

    # Store the Quiz in the MongoDb database
    quiz = Quiz(question, options, right_answer, start_date, end_date)
    result = quizzes_collection.insert_one(quiz.__dict__)
    quiz.id = str(result.inserted_id)

    # print(quiz.__dict__)

    return jsonify({"id": quiz.id}), 201


# 2. GET /quizzes/active - to retrieve the active quiz  -- limit of 10 per minute
# It return the data of all active Quizzes  -- id, question, options
@app.route("/quizzes/active", methods=["GET"])
@limiter.limit("10 per minute")
def get_active_quiz():
    now = datetime.now()

    active_quiz = quizzes_collection.find(
        {"start_date": {"$lte": now}, "end_date": {"$gte": now}},
        {"_id": 1, "question": 1, "options": 1},
    )

    return jsonify(
        [
            {
                "id": str(quiz["_id"]),
                "question": quiz["question"],
                "options": quiz["options"],
            }
            for quiz in active_quiz
        ]
    )


# 3. GET /quizzes/<id>/result - to retrieve the result of a quiz by its ObjectId   -- limit of 10 per minute
# It return the right option of the particular Quiz if its alocated time and additional 5 minutes has past -- right_answer 
@app.route("/quizzes/<string:quiz_id>/result", methods=["GET"])
@limiter.limit("10 per minute")
def get_quiz_result(quiz_id):
    try:
        quiz = quizzes_collection.find_one({"_id": ObjectId(quiz_id)})

        if not quiz:
            abort(404, "Quiz result not found")

        now = datetime.now()
        result_available_time = quiz["end_date"] + timedelta(minutes=5)

        if now < result_available_time:
            abort(403, "Result not available yet! Try after the quiz has ended.")

        return jsonify({"result": quiz["right_answer"]})

    except InvalidId:
        abort(400, "Invalid quiz ID")


# 4. GET /quizzes/all - to retrieve all quizzes   -- limit of 10 per minute
# It return the data of all Quizzes  -- id, question, options
@app.route("/quizzes/all", methods=["GET"])
@limiter.limit("10 per minute")
def get_all_quizzes():
    all_quizzes = quizzes_collection.find({}, {"_id": 1, "question": 1, "options": 1})

    return jsonify(
        [
            {
                "id": str(quiz["_id"]),
                "question": quiz["question"],
                "options": quiz["options"],
            }
            for quiz in all_quizzes
        ]
    )


# 5. Error handling
@app.errorhandler(400)
@app.errorhandler(404)
def handle_error(error):
    response = jsonify({"error": str(error)})
    response.status_code = error.code
    return response


# App is run from here
if __name__ == "__main__":
    app.run()
