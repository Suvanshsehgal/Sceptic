import os


def remove_upload(path):
    """Deletes an uploaded file at the given path."""
    os.system("rm -f " + path)
