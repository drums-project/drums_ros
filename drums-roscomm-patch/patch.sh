#!/bin/bash

if [ "$UID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

if [ -z $1 ]; then
    echo "Please provide the prefix."
    exit 1
fi

if [ -z $2 ]; then
    echo "Please provide ROS distro"
    exit 1
fi

if [ $3 = "--backup" ]; then
    backup="--backup"
else
    backup=""
fi

cat list.txt | xargs -L1 -I {} ./drums-roscomm-patch.py -i {} -distro $2 --prefix $1 $backup

