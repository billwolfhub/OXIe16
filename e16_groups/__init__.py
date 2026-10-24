import importlib

from . import E16 as _e16_module


def create_instance(c_instance):
    # Live caches imported modules, so re-selecting the script would otherwise
    # keep running stale code after an edit. Reloading here makes
    # "None -> e16_groups" in Live's settings pick up changes to E16.py.
    importlib.reload(_e16_module)
    return _e16_module.E16(c_instance)
