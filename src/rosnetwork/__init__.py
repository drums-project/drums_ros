# -*- coding: utf-8 -*-

import rospy
import rosgraph.impl.graph
import socket
import xmlrpclib
import time
import sys
import re
from multiprocessing import Process, Queue, Event
from Queue import Empty, Full
import time
import traceback
#from gevent import Greenlet as Process
#from gevent.queue import Queue, Empty
#from gevent.event import Event

from pprint import pprint

try: #py3k
    import urllib.parse as urlparse
except ImportError:
    import urlparse

NODE_NAME = "drums_ros"

# From rosnode
def _succeed(args):
    code, msg, val = args
    if code != 1:
        #CRITICAL: FIX THIS
        raise ROSNodeException("remote call failed: %s"%msg)
    return val

meta_map = dict()

class RosEntity(object):
    global meta_map
    def __init__(self):
        self.uid = None

    def set_uid(self, uid, meta):
        self.uid = uid
        meta_map[uid] = meta

class RosHost(RosEntity):
    def __init__(self, host):
        RosEntity.__init__(self)
        self.host = host
        self.set_uid(host, '')


def deanonymize_node(name):
    name_deanonymize, count = re.subn("_\d+$", "", name)
    if count == 0:
        return name
    else:
        return deanonymize_node(name_deanonymize)

class RosNode(RosEntity):
    def __init__(self, host, name, pid, deanonymize=True):
        RosEntity.__init__(self)
        self.name = deanonymize_node(name) if deanonymize else name
        self.host = host
        self.pid = pid
        uid = "%s,%s" % (host, pid)
        meta = self.name
        self.set_uid(uid, meta)

class RosLink(RosEntity):
    def __init__(self, conn_mode, topic, direction, local_node, local_host, local_port, remote_node, remote_host, remote_port, deanonymize=True):
        RosEntity.__init__(self)
        self.conn_mode = conn_mode
        self.topic = topic
        self.direction = direction
        self.local_node = deanonymize_node(local_node) if deanonymize else local_node
        self.local_host = local_host
        self.local_port = local_port
        self.remote_node = deanonymize_node(remote_node) if deanonymize else remote_node
        self.remote_host = remote_host
        self.remote_port = remote_port
        uid = "%s,%s,%s,%s,%s" % (
            self.local_host,
            self.conn_mode,
            self.direction,
            self.local_port,
            self.remote_port)
        #meta = "%s,%s,%s,%s" % (topic, local_node, remote_host, remote_node)
        meta = "%s,topic,%s,%s,%s" % (
            self.local_node,
            self.topic,
            "to" if self.direction=='o' else "from",
            #remote_node.replace("http://", "").replace("/", ",").replace(":", ",")
            self.remote_node.replace("http://", "").replace(":", "/")
            )
        self.set_uid(uid, meta)

"""
old: list of RosEntities
cur: list of RosEntities
@output:  a tuple of two lists new, del; each tuple is a list of tuples (uid, meta)
"""
def diff_entity_lists(old, cur):
    global meta_map
    # old and cur are lists
    # returns (new, del) tuple of sets
    def diff_lists(old, cur):
        c = set(cur)
        o = set(old)
        return (c - o, o - c)

    add_entities, del_entities = diff_lists(
            [l.uid for l in old],
            [l.uid for l in cur])

    #return (zip(add_entities, ['' for e in add_entities]), zip(del_entities, ['' for e in del_entities]))
    return (zip(add_entities, [meta_map.get(uid, '') for uid in add_entities]), zip(del_entities, ['' for uid in del_entities]))

class RosNetwork(Process):
    def __init__(self, default_interval, comm_queue):
        Process.__init__(self)
        assert default_interval > 0
        self._default_interval = default_interval
        self.q = comm_queue
        self._last_loop_time = time.time()
        self._terminate_event = Event()

        self._graph = None

        # Ros Entities
        self.nodes = list()
        self.links = list()
        self.hosts = list()
        self.old_nodes = list()
        self.old_links = list()
        self.old_hosts = list()

        self.__regex_local_port = re.compile("port ([0-9]+)")
        self.__regex_remote_host_port = re.compile("\[(.+)\:([0-9]+)")

    def __repr__(self):
        name =  self.__class__.__name__
        return '<%s at %#x>' % (name, id(self))

    def set_terminate_event(self):
        self._terminate_event.set()


    def get_uri(self, node_name):
        return self._graph.node_uri_map[node_name]

    def get_node_pid(self, node_name):
        socket.setdefaulttimeout(5.0)
        node = xmlrpclib.ServerProxy(self.get_uri(node_name))
        return _succeed(node.getPid(NODE_NAME))

    def get_node_host(self, node_name):
        return urlparse.urlparse(self.get_uri(node_name)).hostname

    def get_node_bus_info(self, node_name):
        socket.setdefaulttimeout(5.0)
        node = xmlrpclib.ServerProxy(self.get_uri(node_name))
        return _succeed(node.getBusInfo(NODE_NAME))

    def update(self):
        global meta_map
        try:
            self._graph = rosgraph.impl.graph.Graph()
            self._graph.set_master_stale(5.0)
            self._graph.set_node_stale(5.0)
            self._graph.update()

            self.old_nodes = self.nodes[:]
            self.nodes = []

            self.old_hosts = self.hosts[:]
            self.hosts = []

            self.old_links = self.links[:]
            self.links = []

            # TODO: Parallelize this
            for n in self._graph.nn_nodes:
                pid = self.get_node_pid(n)
                host = self.get_node_host(n)
                self.hosts.append(RosHost(host))
                self.nodes.append(RosNode(host, n, pid))

                links = self.get_node_bus_info(n)
                # Sample: https://gist.github.com/mani-monaj/81e74a64185a19fb3684
                for l in links:
                    try:
                        local_port, = self.__regex_local_port.search(l[6]).groups()
                        remote_host, remote_port = self.__regex_remote_host_port.search(l[6]).groups()
                        # l[1] is
                        # XMLRPC URI of Publisher for Subscribers
                        # CallerID (node name) of Subscriber for Publisher
                        remote_node = l[1]
                        if remote_node.find("http://") == 0:
                            # If remote node is XMLRPC URI, find the node name
                            remote_node = self._graph.uri_node_map.get(remote_node, remote_node)

                        self.links.append(
                            RosLink(
                                conn_mode=l[3],
                                topic=l[4],
                                direction=l[2],
                                local_node=n,
                                local_host=host,
                                local_port=local_port,
                                remote_node=remote_node,
                                remote_host=remote_host,
                                remote_port=remote_port))
                    except AttributeError, e:
                        #print "AttributeError `%s` for node `%s`" % (e, n)
                        #print l
                        pass#rospy.logwarn("The result of getBusInfo() does not include detailed bus information.")
                    except IndexError:
                        #print "IndexError"
                        pass#rospy.logwarn("Format error while parsing getBusInfo()")
                time.sleep(0.01)

            self.hosts = list(set(self.hosts))

            new_nodes, del_nodes = diff_entity_lists(
                self.old_nodes, self.nodes)
            new_hosts, del_hosts = diff_entity_lists(
                self.old_hosts, self.hosts)
            new_links, del_links = diff_entity_lists(
                self.old_links, self.links)

            for host_uid, meta in new_hosts:
                self.q.put(('host', 'new', host_uid, meta))

            for host_uid, meta in del_hosts:
                self.q.put(('host', 'del', host_uid, meta))
                del meta_map[host_uid]

            for node_uid, meta in new_nodes:
                self.q.put(
                    ('node', 'new', node_uid, meta))

            for node_uid, meta in del_nodes:
                self.q.put(
                    ('node', 'del', node_uid, meta))
                del meta_map[node_uid]

            for link_uid, meta in new_links:
                self.q.put(
                    ('link', 'new', link_uid, meta))

            for link_uid, meta in del_links:
                self.q.put(
                    ('link', 'del', link_uid, meta))
                del meta_map[link_uid]

        except rosgraph.MasterError:
            rospy.logwarn("Unable to commuincate with master, will try again.")
            self.nodes = self.old_nodes[:]
            self.hosts = self.old_hosts[:]
            self.links = self.old_links[:]
        except  socket.error:
            rospy.logwarn("Socket.error when communicationg with master, will try again.")
            self.nodes = self.old_nodes[:]
            self.hosts = self.old_hosts[:]
            self.links = self.old_links[:]

    # THIS RUNS IN A SEPERATE PROCESS. All class variables are local in this process
    def run(self):
        rospy.loginfo("Ros graph monitor started.")
        try:
            self._last_loop_time = time.time()
            while not self._terminate_event.is_set():
                #rospy.loginfo("Update ROS system state ...")
                self.update()

                diff = time.time() - self._last_loop_time
                sleep_time = self._default_interval - diff
                try:
                    time.sleep(sleep_time)
                except:
                    rospy.logwarn("Default interval for rosgraphmonitor is too small (%s). Last loop: %s" % (self._default_interval, diff))
                self._last_loop_time = time.time()
            rospy.loginfo("Rosgraph monitor exited cleanly.")
            return True
        except:
            rospy.loginfo("rosgraphmonitor exited with '%s' : %s" %
                (sys.exc_info()[0], sys.exc_info()[1]))
            traceback.print_exc()#rospy.loginfo("Call Stack:")
            #traceback.print_stack(sys.exc_info()[2])
            #rospy.loginfo("%s" % traceback.extract_tb(sys.exc_info()[2]))

    def get_nodes(self):
        return self._diff_lists(
            [n.uid for n in self.old_nodes],
            [n.uid for n in self.nodes])

    def get_hosts(self):
        return self._diff_lists(self.old_hosts, self.hosts)

    def get_links(self):
        return self._diff_lists(
            [l.uid for l in self.old_links],
            [l.uid for l in self.links])
