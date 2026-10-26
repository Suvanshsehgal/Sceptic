import pickle


def load_session(blob):
    """Restores a session object from a stored blob."""
    return pickle.loads(blob)
