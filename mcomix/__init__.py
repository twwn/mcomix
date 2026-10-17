import time

#: When MComix' own code began to run, by time.monotonic(): the
#: modules imported from here on load GLib's libraries, which on
#: Windows can take long enough to be worth telling from the wait
#: before Python ran at all.
started = time.monotonic()
#: The processor time the process had used by then, by
#: time.process_time(), which counts it from the process' creation:
#: set beside the time taken, it tells waiting - for the disk, or for
#: an antivirus, which scans in a process of its own - from computing.
started_on_cpu = time.process_time()
