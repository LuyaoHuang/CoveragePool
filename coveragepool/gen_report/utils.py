import subprocess
import re
import platform

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd.split())
    except subprocess.CalledProcessError as e:
        raise Exception('Fail to run cmd %s, reason: %s' % (e.cmd, e.output))

def parse_package_name(package_name):
    match = re.match(
        r"^(.+)\.([^.]+)$", package_name)
    if not match:
        raise Exception('Package %s can not be parsed' % package_name)

    nvr, arch = match.groups()
    match = re.match(r"^(.+)-([^-]+)-([^-]+)$", nvr)
    if not match:
        raise Exception('NVR %s can not be parsed' % nvr)
    name, version, release = match.groups()
    return name, version, release, arch

def check_package_version(name):
    cmd = 'rpm -q ' + name
    out = run_cmd(cmd)
    return out[:-1]

def trans_distro_info():
    info = platform.linux_distribution()
    if 'Red Hat Enterprise Linux' in info[0]:
        tmp = info[1].split('.')
        return 'el%s' % tmp[0]
    else:
        raise Exception('Not support %s right now' % info[0])

