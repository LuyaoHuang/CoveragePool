import os
import re
import shutil
import tempfile
import subprocess
from contextlib import contextmanager
from .utils import run_cmd, parse_package_name, check_package_version, trans_distro_info

class BaseCoverageHelper(object):
    def prepare_env(self):
        raise NotImplementedError('prepare_env')
    def periodic_check(self):
        raise NotImplementedError('periodic_check')
    def gen_report(self):
        raise NotImplementedError('gen_report')
    def merge_tracefile(self):
        raise NotImplementedError('merge_report')
    def convert_tracefile(self):
        raise NotImplementedError('convert_tracefile')

class BaseCoverageEnv(object):
    def prepare_env(self):
        raise NotImplementedError('prepare_env')
    def clean_up_env(self):
        pass

class RpmCoverageEnv(BaseCoverageEnv):
    def prepare_env(self, packages):
        rm_list = []
        install_list = []
        for package in packages:
            try:
                name, version, release, _ = parse_package_name(package)
                rm_list.append(name)
                install_list.append('%s-%s-%s' % (name, version, release))
            except:
                rm_list.append(package)
                install_list.append(package)

        pre_cmd = 'yum remove -y %s' % (' '.join(rm_list))
        cmd = 'yum install -y %s' % (' '.join(install_list))
        run_cmd(pre_cmd)
        run_cmd(cmd)

class Rpm2cpioCoverageEnv(BaseCoverageEnv):
    def __init__(self):
        self.tmp_work_dir = None

    def prepare_env(self, packages):
        tmp_work_dir = tempfile.mkdtemp()
        for package in packages:
            try:
                cmd = 'yumdownloader -q --urls %s' % package
                out = run_cmd(cmd)

                old_path = os.getcwd()
                try:
                    os.chdir(tmp_work_dir)
                    pkg = '%s.rpm' % package
                    cmd = 'wget %s -O %s' % (out[:-1], pkg)
                    run_cmd(cmd)
                    p = subprocess.Popen(('rpm2cpio', pkg), stdout=subprocess.PIPE)
                    subprocess.check_output(('cpio', '-ivdm'), stdin=p.stdout, stderr=subprocess.STDOUT)
                    os.remove(pkg)
                finally:
                    os.chdir(old_path)

            except Exception as e:
                shutil.rmtree(tmp_work_dir)
                raise e

        self.tmp_work_dir = tmp_work_dir
        return tmp_work_dir

    def clean_up_env(self):
        if self.tmp_work_dir:
            shutil.rmtree(self.tmp_work_dir)

def prepare_git_repo(git_repo, base_dir, work_dir, commit=None):
    if os.path.exists(base_dir):
        git_dir = os.path.join(base_dir, '.git')
        cmd = 'git --git-dir %s --work-tree %s pull' % (git_dir, base_dir)
    else:
        cmd = 'git clone %s %s' % (git_repo, base_dir)

    run_cmd(cmd)
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(base_dir, work_dir)

    if commit:
        git_dir = os.path.join(work_dir, '.git')
        cmd2 = 'git --git-dir %s --work-tree %s checkout -f %s' % (git_dir, work_dir, commit)
        run_cmd(cmd2)

class GitCoverageEnv(BaseCoverageEnv):
    def __init__(self, name, work_dir, git_repo, base_dir='/usr/share/coveragepool/'):
        self.name = name
        self.work_dir = work_dir
        self.git_dir = os.path.join(work_dir, '.git')
        self.git_repo = git_repo
        self.Base_dir = os.path.join(base_dir, name)

    def prepare_env(self, git_tag):
        prepare_git_repo(self.git_repo, self.Base_dir, self.work_dir, git_tag)

    def get_git_diff(self, src_tag, tgt_tag):
        cmd = 'git --git-dir %s --work-tree %s diff %s %s' % (self.git_dir,
                self.work_dir, src_tag, tgt_tag)
        out = run_cmd(cmd)
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.tmp', prefix='diff-',
            delete=False)
        tmp_file.write(out)
        tmp_file.close()

        return tmp_file.name

    def clean_up_env(self):
        if os.path.exists(self.work_dir):
            shutil.rmtree(self.work_dir)

class DistGitCoverageEnv(BaseCoverageEnv):
    @staticmethod
    def apply_patch(name, dist_work_dir, work_dir):
        """
        If not work as expected, override this function
        """
        spec_file = os.path.join(dist_work_dir, '%s.spec' % name)
        git_dir = os.path.join(work_dir, '.git')
        with open(spec_file) as fp:
            lines = fp.readlines()
        for line in lines:
            match = re.match(r"^Patch([0-9]+): (.+)", line)
            if match:
                _, patch_name = match.groups()
                patch_file = os.path.join(dist_work_dir, patch_name)
                cmd = 'git --git-dir %s --work-tree %s am -3 %s' % (git_dir, work_dir, patch_file)
                run_cmd(cmd)

    def prepare_env(self, name, work_dir, git_repo,
                    git_tag, dist_git_repo, dist_git_tag,
                    base_dir='/usr/share/coveragepool/'):
        Base_dir = os.path.join(base_dir, name)
        prepare_git_repo(git_repo, Base_dir, work_dir, git_tag)
        Base_dir = os.path.join(base_dir, '%s-dist-git' % name)
        dist_work_dir = tempfile.mkdtemp()
        prepare_git_repo(dist_git_repo, Base_dir, dist_work_dir, dist_git_tag)
        self.apply_patch(name, dist_work_dir, work_dir)

class CCoverageHelper(BaseCoverageHelper):
    """
    Use LCOV to generate report
    """
    def replace_tracefile(self, file_path, src, tgt, check_all=True):
        # Work around someone's stupid patch :D
        with open(file_path) as fp:
            lines = fp.readlines()

        for i, line in enumerate(lines):
            if 'SF:' not in line:
                continue
            if src in line:
                lines[i] = line.replace(src, tgt)
            elif tgt in line:
                if not check_all:
                    return

        with open(file_path, 'w') as fp:
            fp.writelines(lines)

    def copy_replace_tracefile(self, file_path, src, tgt, check_all=True):
        with open(file_path) as fp:
            tmp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.tmp', prefix='tracefile-',
                delete=False)
            tmp_file.write(fp.read())
            tmp_file.close()

        self.replace_tracefile(tmp_file.name, src, tgt, check_all)
        return tmp_file.name

    def gen_report(self, tracefile, output_dir, ig_err_src=False):
        cmd = 'genhtml %s --output-directory %s' % (tracefile, output_dir)
        if ig_err_src:
            # TODO: find a way to not use this work around when the source is from git
            cmd += ' --ignore-errors source'
        run_cmd(cmd)

    def merge_tracefile(self, tracefiles, merged_tracefile):
        cmd = 'lcov'
        for i in tracefiles:
            cmd += ' -a %s' % i
        cmd += ' -o %s' % merged_tracefile
        run_cmd(cmd)

    def convert_tracefile(self, src_tf, tgt_tf, diff_file):
        cmd = 'lcov --diff %s %s -o %s' % (src_tf, diff_file, tgt_tf)
        run_cmd(cmd)

class PythonCoverageHelper(BaseCoverageHelper):
    def __init__(self):
        self.cfg_file = None

    def gen_config_file(self, config_list):
        """
        Support config type:
        1. paths: {'type': 'paths', 'info': [path1, path2 ...]}
        """
        strs = ''
        for i in config_list:
            if i['type'] == 'paths':
                strs += '[paths]\nsource =\n'
                for path in i['info']:
                    strs += '    %s\n' % path
                continue
            else:
                raise Exception('Unsupport configure type')

        tmp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.tmp', prefix='coverage-cfg-',
            delete=False)
        tmp_file.write(strs)
        tmp_file.close()
        self.cfg_file = tmp_file.name

    def gen_report(self, tracefile, output_dir, ig_err_src=False):
        run_cmd('coverage erase')

        with open(tracefile) as fp:
            tmp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.tmp', prefix='tracefile-',
                delete=False)
            tmp_file.write(fp.read())
            tmp_file.close()

        cmd = 'coverage combine'
        if self.cfg_file:
            cmd += ' --rcfile=%s' % self.cfg_file
        cmd += ' %s' % tmp_file.name
        run_cmd(cmd)

        cmd = 'coverage html -d %s' % output_dir
        if ig_err_src:
            cmd += ' -i'
        run_cmd(cmd)

    def merge_tracefile(self, tracefiles, merged_tracefile):
        run_cmd('coverage erase')

        cmd = 'coverage combine'
        tmp_trace_files = []
        if self.cfg_file:
            cmd += ' --rcfile=%s' % self.cfg_file
        for i in tracefiles:
            with open(i) as fp:
                tmp_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.tmp', prefix='tracefile-',
                    delete=False)
                tmp_file.write(fp.read())
                tmp_file.close()
            cmd += ' %s' % tmp_file.name
            tmp_trace_files.append(tmp_file.name)

        try:
            run_cmd(cmd)
        except Exception as e:
            for trace_file in tmp_trace_files:
                os.unlink(trace_file)
            raise e

        shutil.copy('.coverage', merged_tracefile)

    def convert_tracefile(self, src_tf, tgt_tf, diff_file):
        raise Exception('Not support convert trace file')

class LibvirtCoverageHelper(CCoverageHelper):
    def __init__(self, config_params):
        self.tag_fmt = config_params.get('tag_fmt')
        self.git_repo = config_params.get('git_repo')
        self.env = None
        self.old_src_dir = None
        self.new_src_dir = None

    def _prepare_virtcov_env(self, work_dir):
        shutil.rmtree(work_dir)
        run_cmd('virtcov -s')

    @contextmanager
    def prepare_env(self, version_name):
        tag_fmt = self.tag_fmt
        git_repo = self.git_repo

        name, version, release, arch = parse_package_name(version_name)
        if name != 'libvirt':
            raise Exception('This is not libvirt report: %s' % name)

        work_dir = '/mnt/coverage/BUILD/libvirt-%s/' % version
        try:
            self.env = Rpm2cpioCoverageEnv()
            if 'el6' in release:
                tmp_work_dir = self.env.prepare_env(
                        ['libvirt-devel-%s-%s' % (version, release)])
                src_dir = 'usr/share/doc/libvirt-devel-%s/gcno/' % version
            elif 'el7' in release:
                tmp_work_dir = self.env.prepare_env(
                        ['libvirt-docs-%s-%s' % (version, release)])
                src_dir = 'usr/share/doc/libvirt-docs-%s/gcno/' % version
            else:
                raise Exception('Unsupport distro type')

            self.old_src_dir = work_dir
            self.new_src_dir = os.path.join(tmp_work_dir, src_dir)
        except Exception as e:
            #TODO: logging

            # Git base
            self.env = GitCoverageEnv(name, work_dir, git_repo)
            git_tag = tag_fmt.format(name, version, release, arch)
            self.env.prepare_env(name, git_tag)
            self._extra_prepare(work_dir)

            yield
        finally:
            if self.env:
                self.env.clean_up_env()

    def periodic_check(self):
        raise NotImplementedError('periodic_check')

    def gen_report(self, tracefile, output_dir):
        CCoverageHelper.replace_tracefile(self, tracefile, '/usr/coverage/', '/mnt/coverage/')
        if self.new_src_dir:
            tmp_tracefile = CCoverageHelper.copy_replace_tracefile(self, tracefile,
                                                                   self.old_src_dir, self.new_src_dir)
            CCoverageHelper.gen_report(self, tmp_tracefile, output_dir, True)
        else:
            CCoverageHelper.gen_report(self, tracefile, output_dir, True)

    def _extra_prepare(self, work_dir):
        cmd = 'perl -w %s -k remote REMOTE %s' % (os.path.join(work_dir, 'src/rpc/gendispatch.pl'),
                                                  os.path.join(work_dir, 'src/remote/remote_protocol.x'))
        out = run_cmd(cmd)
        with open(os.path.join(work_dir, 'src/remote/remote_client_bodies.h'), 'w') as fp:
            fp.write(out)

        cmd = 'perl -w %s -k qemu QEMU %s' % (os.path.join(work_dir, 'src/rpc/gendispatch.pl'),
                                              os.path.join(work_dir, 'src/remote/qemu_protocol.x'))
        out = run_cmd(cmd)
        with open(os.path.join(work_dir, 'src/remote/qemu_client_bodies.h'), 'w') as fp:
            fp.write(out)

        cmd = 'perl -w %s -b remote REMOTE %s' % (os.path.join(work_dir, 'src/rpc/gendispatch.pl'),
                                                  os.path.join(work_dir, 'src/remote/remote_protocol.x'))
        out = run_cmd(cmd)
        with open(os.path.join(work_dir, 'daemon/remote_dispatch.h'), 'w') as fp:
            fp.write(out)

        cmd = 'perl -w %s -b qemu QEMU %s' % (os.path.join(work_dir, 'src/rpc/gendispatch.pl'),
                                              os.path.join(work_dir, 'src/remote/qemu_protocol.x'))
        out = run_cmd(cmd)
        with open(os.path.join(work_dir, 'daemon/qemu_dispatch.h'), 'w') as fp:
            fp.write(out)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -h %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/remote/remote_protocol.x'),
                         os.path.join(work_dir, 'src/remote/remote_protocol.h'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -c %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/remote/remote_protocol.x'),
                         os.path.join(work_dir, 'src/remote/remote_protocol.c'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -h %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/remote/qemu_protocol.x'),
                         os.path.join(work_dir, 'src/remote/qemu_protocol.h'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -c %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/remote/qemu_protocol.x'),
                         os.path.join(work_dir, 'src/remote/qemu_protocol.c'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -h %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/rpc/virkeepaliveprotocol.x'),
                         os.path.join(work_dir, 'src/rpc/virkeepaliveprotocol.h'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -c %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/rpc/virkeepaliveprotocol.x'),
                         os.path.join(work_dir, 'src/rpc/virkeepaliveprotocol.c'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -h %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/rpc/virnetprotocol.x'),
                         os.path.join(work_dir, 'src/rpc/virnetprotocol.h'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -c %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/rpc/virnetprotocol.x'),
                         os.path.join(work_dir, 'src/rpc/virnetprotocol.c'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -h %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/lxc/lxc_protocol.x'),
                         os.path.join(work_dir, 'src/lxc/lxc_protocol.h'),)
        out = run_cmd(cmd)

        cmd_fmt = 'perl -w %s /usr/bin/rpcgen -c %s %s'
        cmd = cmd_fmt % (os.path.join(work_dir, 'src/rpc/genprotocol.pl'),
                         os.path.join(work_dir, 'src/lxc/lxc_protocol.x'),
                         os.path.join(work_dir, 'src/lxc/lxc_protocol.c'),)
        out = run_cmd(cmd)

class VirtinstCoverageHelper(PythonCoverageHelper):
    def __init__(self, config_params):
        self.tag_fmt = config_params.get('tag_fmt')
        self.git_repo = config_params.get('git_repo')
        self.env = None

    @contextmanager
    def prepare_env(self, version_name):
        tag_fmt = self.tag_fmt
        git_repo = self.git_repo

        name, version, release, arch = parse_package_name(version_name)

        self.env = Rpm2cpioCoverageEnv()
        try:
            if 'el6' in release:
                tmp_work_dir = self.env.prepare_env(
                        ['python-virtinst-%s-%s' % (version, release)])
            elif 'el7' in release:
                tmp_work_dir = self.env.prepare_env(
                        ['virt-install-%s-%s' % (version, release),
                         'virt-manager-common-%s-%s' % (version, release)])
            else:
                raise Exception('Unsupport distro type')

            tmp_work_dir = os.path.join(tmp_work_dir, 'usr/')
            config_list = [{'type': 'paths',
                            'info': [tmp_work_dir, '/usr/']},]
            PythonCoverageHelper.gen_config_file(self, config_list)

            yield
        finally:
            self.env.clean_up_env()

    def gen_report(self, tracefile, output_dir):
        PythonCoverageHelper.gen_report(self, tracefile, output_dir, True)
