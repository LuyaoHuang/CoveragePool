from __future__ import absolute_import, unicode_literals
from celery import shared_task, Task
from celery.decorators import task, periodic_task
from celery.task.schedules import crontab
from celery.utils.log import get_task_logger

import os
import re
import subprocess
import platform
import shutil
import tempfile
from dateutil import parser
import time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coveragepool.settings")

import django
django.setup()
from django.conf import settings

from upload.google_api import GoogleSheetMGR
from upload.models import CoverageFile, CoverageReport
from .utils import run_cmd, parse_package_name, check_package_version, trans_distro_info

logger = get_task_logger(__name__)

class CallbackTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Success")
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.info("Fail")

class CoverageReportCB(CallbackTask):
    def on_success(self, retval, task_id, args, kwargs):
        super(CoverageReportCB, self).on_success(retval, task_id, args, kwargs)
        obj_id, output_dir = args
        obj = CoverageFile.objects.get(id=obj_id)
        base_dir = getattr(settings, "COVERAGE_BASE_DIR", None)
        base_url = getattr(settings, "COVERAGE_BASE_URL", None)

        if not base_dir:
            return

        date = parser.parse(time.ctime()).replace(tzinfo=None)
        cr = CoverageReport.objects.create(name=obj.name,
                version=obj.version, date=date)

        try:
            cr.coverage_files.add(obj)
            target = os.path.join(base_dir, str(cr.id))
            shutil.copytree(output_dir, target)

            if base_url:
                url = base_url + str(cr.id)
            else:
                url = ''

            cr.path = target
            cr.url = url
            cr.save()

            gs = GoogleSheetMGR()
            if url:
                gs.search_update_by_dict({'Id': obj.id},
                                         {'Coverage Report': url})
            else:
                gs.search_update_by_dict({'Id': obj.id},
                                         {'Coverage Report': 'Sucess'})
        except Exception as detail:
            cr.delete()
            logger.error('Fail to finish successed work: %s' % detail)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        super(CoverageReportCB, self).on_failure(exc, task_id, args, kwargs, einfo)
        obj_id, output_dir = args
        obj = CoverageFile.objects.get(id=obj_id)
        gs = GoogleSheetMGR()
        gs.search_update_by_dict({'Id': obj.id},
                                 {'Coverage Report': 'Fail to generate report'})

def convert_tracefile(file_path, check_all=True):
    # Work around someone's stupid patch :D
    with open(file_path) as fp:
        lines = fp.readlines()

    for i, line in enumerate(lines):
        if 'SF:' in line:
            if '/usr/coverage/' in line:
                lines[i] = line.replace('/usr/coverage/', '/mnt/coverage/')
            elif '/mnt/coverage/' in line:
                if not check_all:
                    return

    with open(file_path, 'w') as fp:
        fp.writelines(lines)

def prepare_env(package_name):
    name, version, release, arch = parse_package_name(package_name)
    if name != 'libvirt':
        raise Exception('Only support libvirt right now')
    tgt_package = check_package_version(name)
    if tgt_package == package_name:
        prepare_virtcov()
        return

    work_dir = '/mnt/coverage/BUILD/libvirt-%s/' % version

    install_package_name = '%s-%s-%s' % (name, version, release)
    distro_info = trans_distro_info()
    if distro_info in release:
        old = True if distro_info == 'el6' else False
        prepare_env_rpm(install_package_name, old)
        prepare_virtcov()
        return work_dir

    # try git
    prepare_env_git(work_dir, package_name)
    return work_dir

def prepare_virtcov():
    remove_cmd = 'rm -rf /mnt/coverage/'
    cmd3 = 'virtcov -s'
    run_cmd(remove_cmd)
    run_cmd(cmd3)

def prepare_env_rpm(package_name, old=False):
    pre_cmd = 'yum remove -y libvirt*'
    cmd = 'yum install -y ' + package_name
    if old:
        cmd2 = 'yum install -y libvirt-devel libvirt-client'
    else:
        cmd2 = 'yum install -y libvirt-docs'

    run_cmd(pre_cmd)
    run_cmd(cmd)
    run_cmd(cmd2)

def extra_prepare_libvirt(work_dir):
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

def prepare_env_git(work_dir, package_name, base_dir='/usr/share/coveragepool/'):
    tag_fmt = getattr(settings, "COVERAGE_TAG_FMT", None)
    if not tag_fmt:
        raise Exception('No COVERAGE_TAG_FMT in settings')

    name, version, release, arch = parse_package_name(package_name)
    if 'virtcov' in release:
        release = release.replace('.virtcov', '')
    tag = tag_fmt.format(name, version, release, arch)

    Base_dir = os.path.join(base_dir, name)
    if os.path.exists(Base_dir):
        git_dir = os.path.join(Base_dir, '.git')
        cmd = 'git --git-dir %s --work-tree %s pull' % (git_dir, Base_dir)
    else:
        git_repo = getattr(settings, "COVERAGE_GIT_REPO", None)
        if not tag_fmt:
            raise Exception('No COVERAGE_GIT_REPO in settings')

        cmd = 'git clone %s %s' % (git_repo, Base_dir)

    git_dir = os.path.join(work_dir, '.git')
    cmd2 = 'git --git-dir %s --work-tree %s checkout -f %s' % (git_dir, work_dir, tag)

    run_cmd(cmd)
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(Base_dir, work_dir)
    run_cmd(cmd2)
    extra_prepare_libvirt(work_dir)

def get_git_diff(work_dir, src_pkg, tgt_pkg):
    tag_fmt = getattr(settings, "COVERAGE_TAG_FMT", None)
    if not tag_fmt:
        raise Exception('No COVERAGE_TAG_FMT in settings')

    src_tag = tag_fmt.format(parse_package_name(src_pkg))
    tgt_tag = tag_fmt.format(parse_package_name(tgt_pkg))

    git_dir = os.path.join(work_dir, '.git')
    cmd = 'git --git-dir %s --work-tree %s diff %s %s' % (git_dir, work_dir, src_tag, tgt_tag)
    out = run_cmd(cmd)
    tmp_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.tmp', prefix='diff-',
        delete=False)
    tmp_file.write(out)
    tmp_file.close()

    return tmp_file.name

@task(base=CoverageReportCB)
def gen_coverage_report(obj_id, output_dir):
    shutil.rmtree(output_dir, True)
    # TODO: Ensuring a task is only executed one at a time
    obj = CoverageFile.objects.get(id=obj_id)
    work_dir = prepare_env(obj.version)
    convert_tracefile(obj.coveragefile.path)
    cmd = 'genhtml %s --output-directory %s' % (obj.coveragefile.path, output_dir)
    # TODO: find a way to not use this work around when the source is from git
    cmd += ' --ignore-errors source'
    logger.info('Run cmd: ' + cmd)
    run_cmd(cmd)

class MergeCoverageReportCB(CallbackTask):
    def on_success(self, retval, task_id, args, kwargs):
        super(MergeCoverageReportCB, self).on_success(retval, task_id, args, kwargs)
        obj_ids, output_dir, mobj_id = args
        base_dir = getattr(settings, "COVERAGE_BASE_DIR", None)
        base_url = getattr(settings, "COVERAGE_BASE_URL", None)

        objs = [CoverageFile.objects.get(id=obj_id) for obj_id in obj_ids]

        if not base_dir:
            return

        date = parser.parse(time.ctime()).replace(tzinfo=None)
        if mobj_id:
            cr = CoverageReport.objects.get(id=mobj_id)
        else:
            cr = CoverageReport.objects.create(name='Merged report',
                    version=objs[0].version, date=date)

        old_path = None
        old_tracefile = None
        try:
            for obj in objs:
                cr.coverage_files.add(obj)
            target = os.path.join(base_dir, str(cr.id))
            if os.path.exists(target):
                old_path = os.path.join(base_dir, '%stmp' % str(cr.id))
                shutil.move(target, old_path)
            shutil.copytree(output_dir, target)

            if base_url:
                url = base_url + str(cr.id)
            else:
                url = 'Need set COVERAGE_BASE_URL in settings'

            cr.path = target
            cr.url = url

            old_tracefile = cr.tracefile
            cr.save_tracefile('/tmp/merge.tracefile')
            cr.save()

            gs = GoogleSheetMGR(sheet=1)
            info_dict = {"Id": cr.id,
                         "Name": cr.name,
                         "Version": cr.version,
                         "Date": cr.date.strftime("%Y-%m-%d %H:%M:%S"),
                         "Merged from": '\n'.join([obj.name for obj in cr.coverage_files.all()]),
                         "Coverage Report": url}
            if not mobj_id:
                gs.add_new_row_by_dict(info_dict)
            else:
                gs.search_update_by_dict({'Id': mobj_id}, info_dict)
            if old_path:
                shutil.rmtree(old_path, True)
            if old_tracefile:
                old_tracefile.delete(save=False)

        except Exception as detail:
            logger.error('Fail to finish successed work: %s' % detail)
            if not mobj_id:
                cr.delete()
            else:
                if old_path and cr.path != old_path:
                    shutil.rmtree(cr.path, True)
                    shutil.move(old_path, cr.path)
                if old_tracefile and cr.tracefile != old_tracefile:
                    cr.tracefile.delete(save=False)
                    cr.tracefile = old_tracefile
                for obj in objs:
                    cr.coverage_files.remove(obj)


@task(base=MergeCoverageReportCB)
def merge_coverage_report(obj_ids, output_dir, merge_id=None):
    #TODO: support convert report
    only_version = None
    coverage_files = []
    merge_cmd = 'lcov'
    shutil.rmtree(output_dir, True)

    if merge_id:
        obj = CoverageReport.objects.get(id=merge_id)
        only_version = '.'.join(obj.version.split('.')[:-1])
        if not obj.tracefile:
            coverage_files.extend([i.coveragefile.path for i in obj.coverage_files.all()])
        else:
            merge_cmd += ' -a %s' % obj.tracefile.path

    for obj_id in obj_ids:
        obj = CoverageFile.objects.get(id=obj_id)
        coverage_files.append(obj.coveragefile.path)
        if only_version:
            if only_version != '.'.join(obj.version.split('.')[:-1]):
                raise Exception('Not support merge different coverage: %s != %s',
                                only_version, '.'.join(obj.version.split('.')[:-1]))
        else:
            only_version = '.'.join(obj.version.split('.')[:-1])

    work_dir = prepare_env(obj.version)
    tmp_tracefile = '/tmp/merge.tracefile'
    for i in coverage_files:
        merge_cmd += ' -a %s' % i
    merge_cmd += ' -o %s' % tmp_tracefile
    run_cmd(merge_cmd)
    convert_tracefile(tmp_tracefile)
    cmd = 'genhtml %s --output-directory %s' % (tmp_tracefile, output_dir)
    # TODO: find a way to not use this work around when the source is from git
    cmd += ' --ignore-errors source'
    run_cmd(cmd)

#
# Periodic Tasks
#

@periodic_task(run_every=(crontab(minute='*/15')), name="rescan_table", ignore_result=True)
def rescan_table():
    def _check_obj(objs, table, gs):
        for obj in objs:
            infos = gs.search_info_by_dict({'Id': obj.id}, table)
            if infos:
                if infos[0]['Name'] != obj.name:
                    logger.info('Update %s name to %s' % (str(obj.id), infos[0]['Name']))
                    obj.name = infos[0]['Name']
                    obj.save()
            else:
                logger.info('Cannot find id %s in table, delete it' % str(obj.id))
                obj.delete()

    def _update_merge_report(objs):
        for obj in objs:
            if not obj.coverage_files.all():
                # this is not a merged report, skip it
                continue
            exist_cfs = obj.coverage_files.all()
            if not obj.rules:
                continue
            rules = obj.rules.split(';')
            kargs = {}
            for i in rules:
                kargs[i.split(':')[0]] = i.split(':')[1]
            try:
                cf_objs = CoverageFile.objects.filter(**kargs)
            except:
                logger.error('Fail to find CoverageFile with rules: %s, CoverageReport id: %d' % obj.rules, obj.id)
                continue

            s_exist_cfs = set(exist_cfs)
            new_objs = [i for i in cf_objs if i not in s_exist_cfs]
            merge_coverage_report.delay([i.id for i in new_objs], '/tmp/tmpdir', obj.id)

    objs = CoverageFile.objects.all()
    gs = GoogleSheetMGR()
    table = gs.get_all_values()
    _check_obj(objs, table, gs)

    objs = CoverageReport.objects.all()
    gs = GoogleSheetMGR(sheet=1)
    table = gs.get_all_values()
    _check_obj(objs, table, gs)
    _update_merge_report(objs)
