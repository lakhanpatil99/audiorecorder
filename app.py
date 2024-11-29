from flask import Flask, request, send_from_directory
import os

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return send_from_directory(os.getcwd(), 'index.html')

@app.route('/upload', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return 'No audio file found', 400

    audio_file = request.files['audio']
    
    # Validate MIME type
    if audio_file.content_type not in ['audio/wav', 'audio/x-wav']:
        return 'Invalid file format. Only WAV files are supported.', 400

    file_path = os.path.join(UPLOAD_FOLDER, audio_file.filename)
    audio_file.save(file_path)
    return 'Audio uploaded successfully!', 200

if __name__ == '__main__':
    app.run(debug=True)
