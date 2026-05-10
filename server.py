from dashboard_web import app, start_next_dashboard


if __name__ == "__main__":
    start_next_dashboard()
    app.run(port=4000, debug=False)
