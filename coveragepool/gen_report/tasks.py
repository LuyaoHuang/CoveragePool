from __future__ import absolute_import, unicode_literals
from celery import shared_task, Task
from celery.decorators import task
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
from .utils import run_cmd

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
            target = os.path.join(base_dir, cr.id)
            shutil.copytree(output_dir, target)

            if base_url:
                url = base_url + cr.id
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

def convert_tracefile(file_path):
    # Work around someone's stupid patch :D
    with open(file_path) as fp:
        lines = fp.readlines()

    for i, line in enumerate(lines):
        if 'SF:' in line:
            if '/usr/coverage/' in line:
                lines[i] = line.replace('/usr/coverage/', '/mnt/coverage/')
            elif '/mnt/coverage/' in line:
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

def prepare_env_git(work_dir, package_name, base_dir='/usr/share/coveragepool/'):
    tag_fmt = getattr(settings, "COVERAGE_TAG_FMT", None)
    if not tag_fmt:
        raise Exception('No COVERAGE_TAG_FMT in settings')

    name, _, _, _ = parse_package_name(package_name)
    tag = tag_fmt.format(parse_package_name(package_name))

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
    cmd2 = 'git --git-dir %s --work-tree %s checkout %s' % (git_dir, work_dir, tag)

    run_cmd(cmd)
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(Base_dir, work_dir)
    run_cmd(cmd2)

def get_git_diff(work_dir, src_pkg, tgt_pkg):
    tag_fmt = getattr(settings, "COVERAGE_TAG_FMT", None)
    if not tag_fmt:
        raise Exception('No COVERAGE_TAG_FMT in settings')

    src_tag = tag_fmt.format(parse_package_name(package_name))
    tgt_tag = tag_fmt.format(parse_package_name(package_name))

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
    # TODO: Ensuring a task is only executed one at a time
    obj = CoverageFile.objects.get(id=obj_id)
    work_dir = prepare_env(obj.version)
    cmd = 'genhtml %s --output-directory %s' % (obj.coveragefile.path, output_dir)
    logger.info('Run cmd: ' + cmd)
    run_cmd(cmd)

class MergeCoverageReportCB(CallbackTask):
    def on_success(self, retval, task_id, args, kwargs):
        super(MergeCoverageReportCB, self).on_success(retval, task_id, args, kwargs)
        obj_ids, output_dir = args
        base_dir = getattr(settings, "COVERAGE_BASE_DIR", None)
        base_url = getattr(settings, "COVERAGE_BASE_URL", None)

        objs = [CoverageFile.objects.get(id=obj_id) for obj_id in obj_ids]
        objs_name = [obj.name for obj in objs]

        if not base_dir:
            return

        date = parser.parse(time.ctime()).replace(tzinfo=None)
        cr = CoverageReport.objects.create(name='Merged report',
                version=objs[0].version, date=date)

        try:
            for obj in objs:
                cr.coverage_files.add(obj)
            target = os.path.join(base_dir, cr.id)
            shutil.copytree(output_dir, target)

            if base_url:
                url = base_url + cr.id
            else:
                url = ''

            cr.path = target
            cr.url = url
            cr.save()

            if not url:
                return

            gs = GoogleSheetMGR(sheet=1)
            gs.add_new_row_by_dict({"Id": cr.id,
                                    "Name": cr.name,
                                    "Version": cr.version,
                                    "Date": cr.date.strftime("%Y-%m-%d %H:%M:%S"),
                                    "Merged from": '\n'.join(objs_name),
                                    "Coverage Report": url})
        except Exception as detail:
            cr.delete()
            logger.error('Fail to finish successed work: %s' % detail)


@task(base=MergeCoverageReportCB)
def merge_coverage_report(obj_ids, output_dir):
    #TODO: support convert report
    only_version = None
    coverage_files = []
    for obj_id in obj_ids:
        obj = CoverageFile.objects.get(id=obj_id)
        coverage_files.append(obj.coveragefile.path)
        if only_version:
            if only_version != '.'.join(obj.version.split('.')[:-1]):
                raise Exception('Not support merge different coverage')
        else:
            only_version = '.'.join(obj.version.split('.')[:-1])

    work_dir = prepare_env(obj.version)
    tmp_tracefile = '/tmp/merge.tracefile'
    merge_cmd = 'lcov'
    for i in coverage_files:
        merge_cmd += ' -a %s' % i
    merge_cmd += ' -o %s' % tmp_tracefile
    run_cmd(merge_cmd)
    cmd = 'genhtml %s --output-directory %s' % (tmp_tracefile, output_dir)
    run_cmd(cmd)
