DATABASE_PASSWORD = "Pr0d-hunter2-secret"


def connect_info():
    """Returns connection settings for the reporting database."""
    return {"user": "reporter", "password": DATABASE_PASSWORD}
