from flask import Flask, jsonify, render_template, request
from alert_logic import run_alert_pipeline
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable frontend -> backend communication

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/run-alert', methods=['POST'])
def run_alert():
    try:
        alert_message = run_alert_pipeline()
        return jsonify({"message": alert_message})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/magnitude-data")
def magnitude_data():
    import pandas as pd
    df = pd.read_csv("predicted_earthquakes_with_impact.csv")

    df = df[["time", "predicted_mag"]].dropna()
    df["time"] = pd.to_datetime(df["time"]).astype(str)

    return jsonify({
        "time": df["time"].tolist(),
        "magnitude": df["predicted_mag"].tolist()
    })


if __name__ == '__main__':
    app.run(debug=True)
