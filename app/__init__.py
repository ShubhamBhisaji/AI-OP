"""
app/ — AetheerAI application entry points.

This package contains thin launchers that wire the AetheerAI system
together and expose it to the outside world.  All heavy business logic
lives in AetheerAI/ (or src/aetheerai/).

Entry points
------------
  app/cli.py         →  python app/cli.py
  app/dashboard.py   →  streamlit run app/dashboard.py
  app/server.py      →  uvicorn app.server:app --reload
"""
