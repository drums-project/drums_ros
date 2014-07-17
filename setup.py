#!/usr/bin/env python
## ! DO NOT MANUALLY INVOKE THIS setup.py, USE CATKIN INSTEAD
# From: http://wiki.ros.org/rospy_tutorials/Tutorials/Makefile
from distutils.core import setup
from catkin_pkg.python_setup import generate_distutils_setup

# fetch values from package.xml
setup_args = generate_distutils_setup(
    packages=['rosnetwork', 'drumspy'],
    package_dir={'': 'src'},
    scripts={'scripts/drums_ros.py'},
    requires=['roslib', 'rospy', 'rospy_message_converter', 'diagnostic_updater']
    #requires=['drumspy >= 0.9']
)

setup(**setup_args)
