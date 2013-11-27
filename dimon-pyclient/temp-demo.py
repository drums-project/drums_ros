#!/usr/bin/env python
from dimonpy import *
import gevent
import os
def clbk(d):
    print "[%s: %s: %s] @ %s" % (d['src'], d['type'], d['key'], d['data']['timestamp'])

tasks = []
tasks.append(DimonPID('eva', 8001, pid = os.getpid()))
tasks.append(DimonHost('eva', 8001))
tasks.append(DimonLatency('eva', 8001, target = 'google.co.jp'))
tasks.append(DimonLatency('eva', 8001, target = 'newmarvin'))
tasks.append(DimonSocket('eva', 8001, proto = "udp", direction = "dst", port = 53))

for t in tasks:
	t.register_callback(clbk)
	t.start_monitor()

try:
	spin()
except KeyboardInterrupt:
	print "Keyboard Interrupt"

for t in tasks:
	t.stop_monitor()

killall()
