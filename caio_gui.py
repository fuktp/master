"""Open with the original IT-approved pythonw.exe. No installation occurs."""

from orquestrador_app.portable import main, report_failure

if __name__ == "__main__":
    try:
        raise SystemExit(main(graphical=True))
    except Exception as error:
        raise SystemExit(report_failure(error, graphical=True))
