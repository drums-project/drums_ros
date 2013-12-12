#!/usr/bin/env python
import dimonpy
import gevent
import os
import time
import logging

MACHINE = 'bluemax'

def clbk(d):
    print "[%s: %s: %s] @ %s" % (d['src'], d['type'], d['key'], d['data']['timestamp'])

logging.basicConfig(filename='/tmp/mani.log', level=logging.DEBUG, format='%(asctime)s %(message)s')

dimonpy.init()

tasks = []
tasks.append(dimonpy.DimonPID(MACHINE, 8001, pid = os.getpid()))
tasks.append(dimonpy.DimonHost(MACHINE, 8001))
tasks.append(dimonpy.DimonLatency(MACHINE, 8001, target = 'google.co.jp'))
tasks.append(dimonpy.DimonLatency(MACHINE, 8001, target = 'newmarvin'))
tasks.append(dimonpy.DimonSocket(MACHINE, 8001, proto = "udp", direction = "dst", port = 53))

for t in tasks:
    t.register_callback(clbk)
    t.start_monitor()

try:
    while not dimonpy.is_shutdown():
        time.sleep(0.1)
except KeyboardInterrupt:
    print "Keyboard Interrupt"

for t in tasks:
    t.stop_monitor()

dimonpy.shutdown()
