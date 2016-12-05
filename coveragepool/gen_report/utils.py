import subprocess

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd.split())
    except subprocess.CalledProcessError as e:
        raise Exception('Fail to run cmd %s, reason: %s' % (e.cmd, e.output))
