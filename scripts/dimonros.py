#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from std_msgs.msg import String
import json
import rosnetwork
import multiprocessing
import threading
import dimonpy
import logging
import sys

DIMON_PORT = 8001

class ROS2DimonInterface(threading.Thread):
    def __init__(self, rosgraphmonitor_q, dimon_callback):
        threading.Thread.__init__(self)
        self.rosgraphmonitor_q = rosgraphmonitor_q

        self.terminate_event = threading.Event()

        self.all_hosts = set()
        self.dimon_tasks = dict()
        self.callback = dimon_callback

    def set_terminate_event(self):
        self.terminate_event.set()

    def _register_latency_task(self, src, dst, callback, meta, monitor_self=False):
        if not monitor_self and src == dst:
            return
        uid = "%s:%s" % (src, dst)
        if uid in self.dimon_tasks:
            return
        task = dimonpy.DimonLatency(src, DIMON_PORT, target=dst, meta=meta)
        if task.register_callback(self.callback):
            self.dimon_tasks[uid] = task
            if not task.start_monitor():
                rospy.logerr("Unable to start the latency monitoring task for `%s`" % (uid,))
        else:
            rospy.logerr("Unable to connect to dimon-daemon at `%s:%s`" % (src, DIMON_PORT))

    def add_new_host(self, host, meta):
        task = dimonpy.DimonHost(host, DIMON_PORT, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.dimon_tasks[host] = task
                self.all_hosts.add(host)
                #Add new Latency Monitors
                for h in self.all_hosts:
                   self._register_latency_task(h, host,
                       self.callback, meta, True)
                   self._register_latency_task(host, h,
                       self.callback, meta, False)
            else:
                rospy.logerr("Unable to start the host monitoring task at `%s`" % (host,))
        else:
            rospy.logerr("Unable to connect to dimon-daemon at `%s:%s`" % (host, DIMON_PORT))

    def del_host(self, host):
        try:
            self.dimon_tasks[host].stop_monitor()
            del self.dimon_tasks[host]
            self.all_hosts.remove(host)
        except KeyError:
            rospy.logerr("Host %s not found!" % host)

    def add_new_node(self, uid, meta):
        host, pid = uid.split(',')
        task = dimonpy.DimonPID(host, DIMON_PORT, pid=pid, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.dimon_tasks[uid] = task
            else:
                rospy.logerr("Unable to start the pid monitoring task for `%s` at `%s`" % (pid, host))
        else:
            rospy.logerr("Unable to connect to dimon-daemon at `%s:%s`" % (host, DIMON_PORT))

    def del_node(self, uid):
        host, pid = uid.split(',')
        try:
            self.dimon_tasks[uid].stop_monitor()
            del self.dimon_tasks[uid]
        except KeyError:
            rospy.logerr("pid:host %s:%s not found!"
                % (host, pid))

    def add_new_link(self, uid, meta):
        #topic, direction, local_host, local_node, local_port, remote_host, remote_node, remote_port, conn_mode = uid.split(',')
        local_host, conn_mode, direction, local_port, remote_port = uid.split(',')
        proto = "tcp" if conn_mode == "TCPROS" else "udp"
        direction = "src" if direction == "i" else "dst"

        task = dimonpy.DimonSocket(local_host, DIMON_PORT, proto='tcp',direction=direction, port=local_port, meta=meta)
        if task.register_callback(self.callback):
            if task.start_monitor():
                self.dimon_tasks[uid] = task
            else:
                rospy.logerr("Unable to start the socket monitoring task for `%s:%s:%s` at `%s`" % (proto, direction, local_port, local_host))
        else:
            rospy.logerr("Unable to connect to dimon-daemon at `%s:%s`" % (local_host, DIMON_PORT))

    def del_link(self, uid):
        local_host, conn_mode, direction, local_port, remote_port = uid.split(',')

        try:
            self.dimon_tasks[uid].stop_monitor()
            del self.dimon_tasks[uid]
        except KeyError:
            rospy.logerr("Socket task %s:%s:%s on %s not found!"
                % (conn_mode,direction,local_port,local_host)
                )
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
        length = len(self.dimon_tasks)
        index = 0
        for uid, task in self.dimon_tasks.items():
            index += 1
            rospy.loginfo("[%s / %s] %s" % (index, length, uid))
            task.stop_monitor()

        rospy.loginfo("ROS To Dimon Interface Thread exited cleanly")
        return True

class ProcPublisher(object):
    def __init__(self, root):
        self.publishers = dict()
        self.root = root

    def create_path(self, src, typ, key):
        return ('%s/%s/%s/%s' % (self.root, src, typ, key, )).replace("//", "/")

    def create_new_pub_if_needed(self, path):
        if path in self.publishers:
            return
        self.publishers[path] = rospy.Publisher(path, String)

    def callback(self, data):
        try:
            k = data['data'].get('meta', '')
            if not k:
                k = data['key']
            if isinstance(k, list):
                # This only happens for pub sockets
                # TODO: Think about it
                # meta is like this ["/talker,topic,/chatter,to,/dimonros", "/talker,topic,/rosout,to,/rosout"]
                assert len(k) > 0
                if len(k) == 1:
                    k = k[0]
                else:
                    pub_meta = k[0].split(",")
                    k = "%s,topic,__mux__,%s,__mux__" % (pub_meta[0], pub_meta[3])
            k = str(k).replace(",", "/") # TODO: WTF?
            path = self.create_path(
                data['src'], data['type'], k)
        except KeyError:
            rospy.logwarn("Received data from Dimon is not in valid format.")

        self.create_new_pub_if_needed(path)
        self.publishers[path].publish(String(json.dumps(data['data'])))

if __name__ == "__main__":

    def ros_callback(data):
        #print ">>>> ROS: %s" % threading.current_thread()
        pass
        #rospy.loginfo(data.data)


    dpy_logger = logging.getLogger('dimonpy')
    #dpy_logger.basicConfig('dimondpy.log', level=logging.DEBUG, format='%(asctime)s %(message)s')
    #ch = logging.StreamHandler(sys.stdout)
    hdlr = logging.FileHandler('dimondpy.log')
    formatter = logging.Formatter('%(asctime)s %(message)s')
    hdlr.setFormatter(formatter)
    #ch.setFormatter(formatter)
    dpy_logger.addHandler(hdlr)


    rospy.init_node('dimonros')
    proc_pub = ProcPublisher('/dimon')

    rosgraphmonitor_q = multiprocessing.Queue()
    rn = rosnetwork.RosNetwork(3.0, rosgraphmonitor_q)
    rn.start()

    dt = ROS2DimonInterface(rosgraphmonitor_q, proc_pub.callback)
    dt.start()



    rospy.Subscriber("chatter", String, ros_callback)

    dimonpy.init()

    #print ">>>> MAIN: %s" % threading.current_thread()
    try:
        while (not rospy.is_shutdown()) and (not dimonpy.is_shutdown()):
            rospy.sleep(0.1)
            #sub_key, callback = dimonpy.get_callback_queue().get(block=True)
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
        rospy.loginfo("Trying to kill `%s`" % (dt, ))
        dt.set_terminate_event()
        rosgraphmonitor_q.put((0, 0, 0, 0))
        rospy.loginfo("Waiting for process `%s` to finish." % (dt, ))
        dt.join()

        rospy.loginfo("Trying to kill `%s`" % (rn, ))
        rn.set_terminate_event()
        rospy.loginfo("Waiting for process `%s` to finish." % (rn, ))
        rn.join()

        if not dimonpy.is_shutdown():
            rospy.loginfo("Killing dimonpy thread ...")
            dimonpy.shutdown()

        rospy.loginfo("[bye]")
