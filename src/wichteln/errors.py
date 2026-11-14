"""Exception classes and their exit codes.

A message never contains a participant's name, so ``cli`` may print it.
"""


class WichtelnError(Exception):
    exit_code = 1


class UsageError(WichtelnError):
    exit_code = 1


class ConfigError(WichtelnError):
    exit_code = 1


class SendFailures(WichtelnError):
    exit_code = 2


class StateError(WichtelnError):
    exit_code = 3
