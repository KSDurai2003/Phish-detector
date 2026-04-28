# Silent Guard — Homograph Phishing Detection System

Silent Guard is a comprehensive phishing detection system designed to identify and block homograph attacks and standard phishing URLs. It combines a robust Machine Learning pipeline with a real-time browser extension (available for Chrome and Firefox) and a lightweight Python backend.

## Project Structure

The repository is divided into two main components:

1. **Machine Learning Pipeline (`train_model.py`)**: A comprehensive script to train, evaluate, and export various machine learning models (including XGBoost, LightGBM, CatBoost, SVM, Neural Networks, and a custom LCCDE ensemble) to detect homograph URLs. The best performing model is exported in ONNX format for fast inference.
2. **Browser Extension & Backend (`extension/`)**: 
   - **Backend API (`extension/backend/`)**: A Flask-based REST API (`api_server.py`) that loads the trained ONNX model and serves predictions to the browser extension. It also features a heuristic-based fallback engine for catching general phishing patterns (IP addresses, URL shorteners, suspicious keywords).
   - **Extensions (`extension/chrome/`, `extension/firefox/`)**: Browser extensions that monitor web pages and the address bar in real-time, communicating with the local backend API to alert users of potential phishing threats.

## Features

- **Hybrid Detection Engine**: Utilizes both standard heuristic rules (for common phishing indicators) and a specialized ML model (for sophisticated homograph attacks using Punycode/Unicode manipulations).
- **Comprehensive Feature Extraction**: Calculates URL length, domain entropy, Punycode usage, Unicode script variety, and structural ratios (vowel-consonant, digits, special characters) to feed the models.
- **Cross-Browser Support**: Extensions tailored for both Google Chrome and Mozilla Firefox (Manifest V3).
- **Fast Inference**: Uses ONNX Runtime in the backend to ensure low-latency predictions suitable for real-time browsing.

## Installation & Setup

### 1. Training the Model (Optional)
If you want to train the models yourself using your own dataset:

```bash
pip install -r extension/backend/requirements.txt
# Additional ML packages may be required depending on your environment (xgboost, lightgbm, catboost, skl2onnx)
python train_model.py
```
This will generate `model.onnx`, `scaler_mean.npy`, and `scaler_scale.npy` inside the `ensembled_models/` directory.

### 2. Running the Backend Server
The backend server must be running locally for the extension to work.

```bash
cd extension/backend
pip install -r requirements.txt
python api_server.py
# Or use the provided batch script on Windows:
# start_server.bat
```
The server will start at `http://127.0.0.1:5000`. You can verify it's running by navigating to `http://127.0.0.1:5000/ping`.

### 3. Loading the Browser Extension

**For Chrome:**
1. Open Chrome and navigate to `chrome://extensions/`.
2. Enable "Developer mode" in the top right corner.
3. Click "Load unpacked" and select the `extension/chrome` folder.

**For Firefox:**
1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`.
2. Click "Load Temporary Add-on...".
3. Select the `manifest.json` file inside the `extension/firefox` folder.

## Usage

Once the backend is running and the extension is loaded:
1. Browse the web normally.
2. The extension will automatically scan URLs on the active page and in the address bar.
3. If a phishing or homograph attack is detected, the extension will display a warning notification.

## Testing

You can test the system by opening `extension/backend/test_page.html` or navigating to `http://127.0.0.1:5000/test` while the backend server is running. This page contains various dummy legitimate and phishing links to verify the extension's behavior. Additionally, you can run `python extension/backend/test_workflow.py` to test the API directly.
