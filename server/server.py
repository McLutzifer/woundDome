from flask import Flask, request
import os
import time

app = Flask(__name__)

UPLOAD_ROOT = "captures"

@app.route("/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return "No image part", 400

    image = request.files["image"]

    # Create capture folder per “session”
    session_folder = time.strftime("%Y%m%d_%H%M%S")
    save_dir = os.path.join(UPLOAD_ROOT, session_folder)
    os.makedirs(save_dir, exist_ok=True)

    # Save file with original filename
    filepath = os.path.join(save_dir, image.filename)
    image.save(filepath)

    return "OK", 200


if __name__ == "__main__":
    os.makedirs("captures", exist_ok=True)
    app.run(host="0.0.0.0", port=8000, debug=False)
