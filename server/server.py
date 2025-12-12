from flask import Flask, request
import os
import time

app = Flask(__name__)

UPLOAD_DIR = "captures"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Create ONE session folder when the server starts
#SESSION_FOLDER = time.strftime("%Y%m%d_%H%M%S")
#SAVE_DIR = os.path.join(UPLOAD_ROOT, SESSION_FOLDER)
#os.makedirs(SAVE_DIR, exist_ok=True)


@app.route("/upload", methods=["POST"])
def upload_image():
    '''
    if "image" not in request.files:
        return "No image part", 400

    image = request.files["image"]
    filename = image.filename or f"{int(time.time() * 1000)}.jpg"

    filepath = os.path.join(UPLOAD_DIR, filename)
    image.save(filepath)

    print(f"Saved image to {filepath}")
    return "OK", 200
    '''

    raw = request.data  # RAW JPEG rein

    if not raw:
        return "No data received", 400

    filename = f"{int(time.time() * 1000)}.jpg"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(raw)

    print(f"Saved RAW JPEG to {filepath}")
    return "OK", 200



if __name__ == "__main__":
    #os.makedirs(UPLOAD_ROOT, exist_ok=True)
    app.run(host="0.0.0.0", port=8000, debug=False)
