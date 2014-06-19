#!/usr/bin/env python

import sys
import argparse
import time
from subprocess import call

valid_dists = ['hydro', 'groovy']

__CL_HEADER = '\033[95m'
__CL_OKBLUE = '\033[94m'
__CL_OKGREEN = '\033[92m'
__CL_WARNING = '\033[93m'
__CL_FAIL = '\033[91m'
__CL_ENDC = '\033[0m'


def check_if_file_exists(f):
    try:
        with open(f):
            return True
    except IOError:
        return False

def log_color(color, msg):
    sys.stdout.write(color + msg + __CL_ENDC)

def exec_shell_command(cmd, dry_run=False):
    log_color(__CL_OKBLUE, "Executing `%s` ... \n" % (" ".join(cmd),))
    return 0 if dry_run else call(cmd)

def main():
    parser = argparse.ArgumentParser(description='Drums Temporary ROS Patch and Restore\n Sample: ./drums-roscomm-patch.py -i include/ros/publisher_link.h -distro hydro --prefix install-340f0c90')
    parser.add_argument('-i', help='Source file to copy', action="store",dest='input_file', type=str, required=True)
    parser.add_argument('-distro', help='The target ROS distro', action="store",dest='target_distro', type=str, required=True)
    parser.add_argument('--prefixe', help='The source folder to find files in', action="store",dest='prefix', type=str, required=False)
    parser.add_argument("--backup", help="Create backup before replacing the file.", action="store_true", default=False)
    parser.add_argument("--dry-run", help="Dry run, no action",
                    action="store_true", default=False)

    args = parser.parse_args()

    prefix = args.prefix or ''
    src_file = "./%s/%s" % (prefix, args.input_file)
    ros_path = "/opt/ros/%s/" % args.target_distro
    target_file = ros_path + args.input_file

    if args.backup:
        backup_folder = "./backup/%s" % time.strftime('%d%m%Y')

    if not check_if_file_exists(src_file):
        sys.stderr.write("File %s does not exists.\n" % src_file)
        return 1

    if not args.target_distro in valid_dists:
        sys.stderr.write("Distro %s is not valid ROS distro name or not supported at the moment.\n" % args.target_distro)
        return 2

    if not check_if_file_exists(ros_path + "setup.bash"):
        sys.stderr.write("Distro %s not found on this system.\n" % args.target_distro)
        return 3


    if not check_if_file_exists(target_file):
        sys.stderr.write("Target file %s not found on this system.\n" % target_file)

        return 4

    log_color(__CL_OKGREEN, "Replacing %s with %s\n" % (target_file, src_file))

    if args.backup:
        create_backup_folder = ["mkdir", "-p", backup_folder]
        backup_command = ["cp", "--parents", "--preserve", target_file, backup_folder]
        log_color(__CL_WARNING, "Backing up...\n")
        exec_shell_command(create_backup_folder, args.dry_run)
        exec_shell_command(backup_command, args.dry_run)


    log_color(__CL_WARNING, "Installing ...\n")
    install_command = ["install", "-m", "0644", "-p", "--backup", src_file, target_file ]
    exec_shell_command(install_command, args.dry_run)

    #print args
if __name__ == "__main__":
    main()

