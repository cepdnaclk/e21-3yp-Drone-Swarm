from radar_tracker_backend import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, threaded=True)
#to run pip install -r localization_4cam\backend\requirements.txt
#python localization_4cam\backend\run_radar_tracker.py
#http://127.0.0.1:5050/three