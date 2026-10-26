"""One-shot scheduler/worker entry; never starts a resident graphical agent."""

from orquestrador_app.portable import main, report_failure

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(report_failure(error, graphical=False))
