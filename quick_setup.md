My Setup: Ubuntu 14.04.3, ROS Indigo

`drums-daemon`: runs on every host of your ROS-based infrastructure
`drums_ros`: runs only on one machine (the aggregator machine)

## Setup and run drums-daemon locally (no system-wide installation for testing)

For system-wide installation check [this guide](http://drums-project.github.io/drums_daemon.html#installation).

```
sudo apt-get install python-virtualenv python-pip libpcap-dev

$ mkdir ~/drums_ws
$ cd ~/drums_ws
$ virtualenv venv

$ . venv/bin/activate
$ pip install drums-daemon

# if you don't use a virtualenv and use pip directly to install drums-daemon
# it is possible to simply run `sudo drumsd.py start|stop`
# The virtualenv method is good for testing/debuggin or compiling from the source

$ sudo ./venv/bin/drumsd.py start
$ tail -f /tmp/drums-daemon.log  # for debugging
...
[INFO] (DrumsDaemon) drums-daemon app's main loop started ...
```

## Setup drums_ros


### Compile

```bash
$ cd ~/drums_ws
$ mkdir -p catkin_ws/src
$ cd catkin_ws/src
# I prefer to use catkin_tools over catkin, you can adopt it to use
# catkin_init_workspace and catkin_make instead
$ catkin init
$ git clone https://github.com/drums-project/drums_ros.git
$ rosdep install --from-paths src -i
$ cd ~/drums_ws/catkin_ws
$ catkin build
```

### Run

(Assuming roscore is already running)

```
$ rosrun drums_ros drums_ros.py _export_diagnostics:=True _export_graphite:=True
[INFO] [WallTime: 1455910032.951457] Ros graph monitor started.
[INFO] [WallTime: 1455910033.049698] Event: host, new, sektor,
[INFO] [WallTime: 1455910033.086355] Event: node, new, sektor,18308, /drumsros
[INFO] [WallTime: 1455910033.098785] Event: node, new, sektor,18162, /rosout
[INFO] [WallTime: 1455910043.061307] Event: link, new, sektor,TCPROS,i,48109,33510, /rosout,topic,/rosout,from,/drumsros
[INFO] [WallTime: 1455910043.098903] Event: link, new, sektor,TCPROS,o,33510,48109, /drumsros,topic,/rosout,to,/rosout
```

drums_ros now monitors your ROS network and talks to every drums-daemon on the network, issues monitoring tasks automatically and aggregates the data and exports them to both ROS diagnostics and Graphite (TCP Port 2013)


### Quick sanity test

(while everything is running)

```
$ rosrun roscpp_tutorials talker
$ rosrun roscpp_tutorials listener
$ rosrun rospy_turorials listener
```

`drums_ros` will  notice the changes in your ROS graph and issues the monitoring tasks:

```
[INFO] [WallTime: 1455911073.969464] Event: link, new, sektor,TCPROS,o,49263,51209, /talker,topic,/chatter,to,/listener
[INFO] [WallTime: 1455911073.975418] Event: link, new, sektor,TCPROS,o,49263,51208, /talker,topic,/rosout,to,/rosout
[INFO] [WallTime: 1455911073.982022] Event: link, new, sektor,TCPROS,i,51283,49263, /listener,topic,/chatter,from,/talker
[INFO] [WallTime: 1455911073.991074] Event: link, new, sektor,TCPROS,i,51209,49263, /listener,topic,/chatter,from,/talker
[INFO] [WallTime: 1455911073.997295] Event: link, new, sektor,TCPROS,i,54669,45782, /rosout,topic,/rosout,from,/listener
[INFO] [WallTime: 1455911074.004627] Event: link, new, sektor,TCPROS,o,49263,51283, /talker,topic,/chatter,to,/listener
[INFO] [WallTime: 1455911074.012315] Event: link, new, sektor,TCPROS,i,51208,49263, /rosout,topic,/rosout,from,/talker
[INFO] [WallTime: 1455911074.020338] Event: link, new, sektor,TCPROS,o,45782,54669, /listener,topic,/rosout,to,/rosout
[INFO] [WallTime: 1455911074.026543] Event: link, del, sektor,TCPROS,o,40230,45052,
[INFO] [WallTime: 1455911074.030126] Event: link, del, sektor,TCPROS,i,45052,40230,
```

The logfile for drums-daemon (/tmp/drums-daemon.*) will be populated with new technical information about the monitoring tasks for these three node and their connections

    $ netcat -lp 2013

Shows the data that is being sent to Graphite/Whisper

   $ rosrun rqt_runtime_monitor rqt_runtime_monitor

Shows the same data as ROS diagnostics Key:Value pair
