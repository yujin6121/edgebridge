import json
import os
import time


data_dir = os.getcwd()
log = None


def configure(directory, logger=None):
    global data_dir, log
    data_dir = directory
    log = logger


def data_path(filename):
    return os.path.join(data_dir, filename)


def load_jsonl(filename, key_field):
    store = {}
    path = data_path(filename)
    if not os.path.exists(path):
        return store
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    store[rec[key_field]] = rec
    except Exception as e:
        if log:
            log.error(f'Error loading {filename}: {e}')
    return store


def save_jsonl(filename, store):
    path = data_path(filename)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            for rec in store.values():
                f.write(json.dumps(rec) + '\n')
    except Exception as e:
        if log:
            log.error(f'Error saving {filename}: {e}')


def now_ms():
    return int(time.time() * 1000)
