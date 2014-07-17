#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Copyright 2013 Mani Monajjemi (AutonomyLab, Simon Fraser University)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import roslib
roslib.load_manifest('diagnostic_updater')
import rospy
import diagnostic_msgs
import diagnostic_updater

#import diagnostic_msgs

import json
import multiprocessing
import threading
import logging

import rosnetwork
import drumspy
from drumspy.Exporters import ExporterBase
from drumspy.Exporters.graphite import GraphiteExporter

# TODO: Parameterize me
DRUMS_PORT = 8001


class ROS2DrumsInterface(threading.Thread):
    def __init__(self, rosgraphmonitor_q, drums_callback):
        threading.Thread.__init__(self)
        self.rosgraphmonitor_q = rosgraphmonitor_q

        self.terminate_event = threading.Event()

        self.all_hosts = set()
        self.drums_tasks = dict()
        self.callback = drums_callback

    def set_terminate_event(self):
        self.terminate_event.set()

    def _register_latency_task(
            self, src, dst, callback, meta, monitor_self=False):
        if not monitor_self and src == dst:
            return
        uid = "%s:%s" % (src, dst)
        if uid in self.drums_tasks:
            return
        task = drumspy.DrumsLatency(src, DRUMS_PORT, target=dst, meta=meta)
        if task.register_callback(self.callback):
            self.drums_tasks[uid] = task
            if not task.start_monitor():
                rospy.logerr(
                    "Unable to start the latency monitoring task for \
                    `%s`" % (uid,))
        else:
            rospy.logerr(
                "Unable to connect to drums-daemon at `%s:%s`"
                % (src, DRUMS_PORT))

    def add_new_host(self, host, meta):
        task = drumspy.DrumsHost(host, DRUMS_PORT, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.drums_tasks[host] = task
                self.all_hosts.add(host)
                #Add new Latency Monitors
                for h in self.all_hosts:
                    self._register_latency_task(
                        h, host, self.callback, meta, True)
                    self._register_latency_task(
                        host, h, self.callback, meta, False)
            else:
                rospy.logerr(
                    "Unable to start the host monitoring task at `%s`"
                    % (host,))
        else:
            rospy.logerr(
                "Unable to connect to drums-daemon at `%s:%s`"
                % (host, DRUMS_PORT))

    def del_host(self, host):
        try:
            self.drums_tasks[host].stop_monitor()
            del self.drums_tasks[host]
            self.all_hosts.remove(host)
        except KeyError:
            rospy.logerr("Host %s not found!" % host)

    def add_new_node(self, uid, meta):
        host, pid = uid.split(',')
        task = drumspy.DrumsPID(host, DRUMS_PORT, pid=pid, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.drums_tasks[uid] = task
            else:
                rospy.logerr(
                    "Unable to start the pid monitoring task for \
                    `%s` at `%s`" % (pid, host))
        else:
            rospy.logerr(
                "Unable to connect to drums-daemon at `%s:%s`"
                % (host, DRUMS_PORT))

    def del_node(self, uid):
        host, pid = uid.split(',')
        try:
            self.drums_tasks[uid].stop_monitor()
            del self.drums_tasks[uid]
        except KeyError:
            rospy.logerr(
                "pid:host %s:%s not found!" % (host, pid))

    def add_new_link(self, uid, meta):
        local_host, conn_mode, direction, local_port, remote_port = \
            uid.split(',')
        proto = "tcp" if conn_mode == "TCPROS" else "udp"
        direction = "dst" if direction == "i" else "src"

        task = drumspy.DrumsSocket(
            local_host, DRUMS_PORT,
            proto='tcp', direction=direction,
            port=local_port, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.drums_tasks[uid] = task
            else:
                rospy.logerr(
                    "Unable to start the socket monitoring task for \
                    `%s:%s:%s` at `%s`"
                    % (proto, direction, local_port, local_host))
        else:
            rospy.logerr(
                "Unable to connect to drums-daemon at `%s:%s`"
                % (local_host, DRUMS_PORT))

    def del_link(self, uid):
        local_host, conn_mode, direction, local_port, remote_port = \
            uid.split(',')

        try:
            self.drums_tasks[uid].stop_monitor()
            del self.drums_tasks[uid]
        except KeyError:
            rospy.logerr(
                "Socket task %s:%s:%s on %s not found!"
                % (conn_mode, direction, local_port, local_host))

    def run(self):
        while not self.terminate_event.is_set():
            optype, op, uid, meta = self.rosgraphmonitor_q.get(block=True)
            rospy.loginfo("Event: %s, %s, %s, %s" % (optype, op, uid, meta))

            if optype == 'host':
                host = uid
                if op == 'new':
                    self.add_new_host(host, meta)
                elif op == 'del':
                    self.del_host(host)
            elif optype == 'node':
                if op == 'new':
                    self.add_new_node(uid, meta)
                elif op == 'del':
                    self.del_node(uid)
            elif optype == 'link':
                if op == 'new':
                    self.add_new_link(uid, meta)
                elif op == 'del':
                    self.del_link(uid)

        rospy.loginfo("Stopping All remote monitors ...")
        length = len(self.drums_tasks)
        index = 0
        for uid, task in self.drums_tasks.items():
            index += 1
            rospy.loginfo("[%s / %s] %s" % (index, length, uid))
            task.stop_monitor()

        rospy.loginfo("ROS To Drums Interface Thread exited cleanly")
        return True


# class ProcPublisher(object):
#     def __init__(self, root):
#         self.publishers = dict()
#         self.root = root

#     def create_path(self, src, typ, key):
#         return ('%s/%s/%s/%s' % (self.root, src, typ, key, )).replace("//", "/")

#     def create_new_pub_if_needed(self, path):
#         if path in self.publishers:
#             return
#         self.publishers[path] = rospy.Publisher(path, String)

#     def callback(self, data):
#         #print "callback for ", data['key']
#         try:
#             k = data['data'].get('meta', '')
#             if not k:
#                 k = data['key']
#             if isinstance(k, list):
#                 # This only happens for pub sockets
#                 # TODO: Think about it
#                 # meta is like this
#                 # ["/talker,topic,/chatter,to
#                 # ,/drumsros", "/talker,topic,/rosout,to,/rosout"]
#                 assert len(k) > 0
#                 if len(k) == 1:
#                     k = k[0]
#                 else:
#                     pub_meta = k[0].split(",")
#                     k = "%s,topic,__mux__,%s,__mux__" \
#                         % (pub_meta[0], pub_meta[3])

#             # TODO: WTF?
#             k = str(k).replace(",", "/").replace(".", "_").replace("-", "_")

#             path = self.create_path(
#                 data['src'].replace("-", "_"), data['type'], k)
#         except KeyError:
#             rospy.logwarn("Received data from Drums is not in valid format.")

#         self.create_new_pub_if_needed(path)
#         self.publishers[path].publish(String(json.dumps(data['data'])))

class DiagnosticsExporter(object):
    def __init__(self):
        # List of key, values
        #self.updater = updater
        self.cache = dict()
        self.lock = threading.Lock()

    # Internal Usage
    def _cache_optimized(self, d, path):
        stack = list()
        stack.append((path, d["data"]))
        while stack:
            p, ref = stack.pop()
            if isinstance(ref, dict):
                it = ref.iteritems()
            elif isinstance(ref, list):
                it = enumerate(ref)
            else:
                continue
            for key, val in it:
                np = p + "." + str(key)
                if isinstance(val, (int, long, float)):
                    #print np, val
                    #self.sock.send_string("")
                    with self.lock:
                        self.cache[np] = val
                    #plain text seems smaller in our case
                    #buf.append((np, (self.timestamp, val,),))
                else:
                    stack.append((np, val))

    # This is called by drumspy
    def broadcast(self, message, binary=False):
        try:
            k = message['data'].get('meta', '')
            if not k:
                k = message['key']

            if isinstance(k, list):
                assert len(k) > 0
                if len(k) == 1:
                    k = k[0]
                else:
                    # TODO
                    pub_meta = k[0].split(",")
                    k = "%s,topic,__mux__,%s,__mux__" \
                        % (pub_meta[0], pub_meta[3],)

            k = str(k).replace(",", ".")
            root_key = "drums.%s.%s.%s" % (message['src'], message['type'], k)
            root_key = root_key.replace('/', ':')
            #data = message['data']
            #self.timestamp = message['data']['timestamp']
            #self._send(data, root_key)
            self._cache_optimized(message, root_key)

        except KeyError, e:
            self.logger.info("Key `%s` not found in %s." % (e, message))

    # This is called by diagnostics updater
    def produce(self, stat):
        with self.lock:
            for (np, val) in self.cache.items():
                stat.summary(diagnostic_msgs.msg.DiagnosticStatus.OK, np)
                stat.add(np, val)

        return stat

if __name__ == "__main__":
    dpy_logger = logging.getLogger('drumspy')
    hdlr = logging.FileHandler('/tmp/drumspy.log')
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] (%(name)s) %(message)s')
    hdlr.setFormatter(formatter)
    dpy_logger.addHandler(hdlr)

    rospy.init_node('drumsros')
    drumspy.init()
    diag_updater = diagnostic_updater.Updater()
    diag_updater.setHardwareID("none")
    diag_interface = DiagnosticsExporter()
    diag_updater.add("drums", diag_interface.produce)

    if rospy.get_param("~export_graphite", False):
        rospy.loginfo("Graphite Exported Enabled at Port 2013")
        ge = GraphiteExporter(2013)
        drumspy.add_exporter(ge)

    rosgraphmonitor_q = multiprocessing.Queue()

    dt = ROS2DrumsInterface(rosgraphmonitor_q, diag_interface.broadcast)
    dt.start()

    rn = rosnetwork.RosNetwork(10.0, rosgraphmonitor_q)
    rn.start()

    #rospy.Subscriber("chatter", String, ros_callback)
    drumspy.init()

    #print ">>>> MAIN: %s" % threading.current_thread()
    try:
        while (not rospy.is_shutdown()) and (not drumspy.is_shutdown()):
            rospy.sleep(1.0)
            diag_updater.update()
            #sub_key, callback = drumspy.get_callback_queue().get(block=True)
            #rospy.loginfo(">>>>>>>>> %s" % sub_key)
    except IOError:
        # This is becuse CTRL+C is caught in q.get(),
        # TODO: FIXME
        rospy.logwarn("IOError")
    except KeyboardInterrupt:
        pass
    except rospy.ROSInterruptException:
        pass
    finally:
        rospy.loginfo("Trying to kill `%s`" % (rn, ))
        rn.set_terminate_event()
        rospy.loginfo("Waiting for process `%s` to finish." % (rn, ))
        rn.join()

        rospy.loginfo("Trying to kill `%s`" % (dt, ))
        dt.set_terminate_event()
        rosgraphmonitor_q.put((0, 0, 0, 0))
        rospy.loginfo("Waiting for process `%s` to finish." % (dt, ))
        dt.join()

        if not drumspy.is_shutdown():
            rospy.loginfo("Killing drumspy thread ...")
            drumspy.shutdown()

        rospy.loginfo("[bye]")
