import time

#: When MComix' own code began to run, by time.monotonic(): the
#: modules imported from here on load GLib's libraries, which on
#: Windows can take long enough to be worth telling from the wait
#: before Python ran at all.
started = time.monotonic()
