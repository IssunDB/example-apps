"""Allow ``python -m fraud_detection_stream`` from the app directory."""

from fraud_detection_stream.main import main

if __name__ == "__main__":
    raise SystemExit(main())
