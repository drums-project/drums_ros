#!/usr/bin/env python
import drumspy
import gevent
import os
import time
import logging

MACHINE = 'bluemax'

def clbk(d):
    print "[%s: %s: %s] @ %s" % (d['src'], d['type'], d['key'], d['data']['timestamp'])

logging.basicConfig(filename='dp.log', level=logging.DEBUG, format='%(asctime)s %(message)s')

drumspy.init()

tasks = []
tasks.append(drumspy.DrumsPID(MACHINE, 8001, pid = os.getpid()))
tasks.append(drumspy.DrumsHost(MACHINE, 8001))
#tasks.append(drumspy.DrumsLatency(MACHINE, 8001, target = 'google.co.jp'))
tasks.append(drumspy.DrumsLatency(MACHINE, 8001, target = 'newmarvin'))
tasks.append(drumspy.DrumsSocket(MACHINE, 8001, proto = "udp", direction = "dst", port = 53))

for t in tasks:
    t.register_callback(clbk)
    t.start_monitor()

try:
    while not drumspy.is_shutdown():
        time.sleep(0.1)
except KeyboardInterrupt:
    print "Keyboard Interrupt"

for t in tasks:
    t.stop_monitor()

drumspy.shutdown()
