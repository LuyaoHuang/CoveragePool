from __future__ import absolute_import, unicode_literals
from celery import shared_task, Task
from celery.decorators import task, periodic_task
from celery.task.schedules import crontab
from celery.utils.log import get_task_logger

import os
import shutil
from dateutil import parser
import time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coveragepool.settings")

import django
django.setup()
from django.conf import settings

from upload.google_api import GoogleSheetMGR
from upload.models import CoverageFile, CoverageReport, Project
from .utils import run_cmd, parse_package_name, check_package_version, trans_distro_info
from . import report_helper

logger = get_task_logger(__name__)

def prepare_gsmgr(project=None, sheet=None):
    gs_key = getattr(settings, "COVERAGE_GS_KEY", None)
    gs_json_file = getattr(settings, "COVERAGE_GS_JSON_FILE", None)

    if project:
        gs_key = project.gs_key
        gs_json_file = project.gs_json_file

    if gs_key:
        gs = GoogleSheetMGR(gs_key, json_file=gs_json_file, sheet=sheet)
    else:
        # TODO: logging
        return

    return gs

def load_settings(project=None):
    ret = {}
    set_list = dir(settings)
    for i in set_list:
        if 'COVERAGE_' in i:
            name = i[9:].lower()
            val = getattr(settings, i)
            if project:
                p_val = getattr(project, name, None)
                if p_val:
                    val = p_val
            ret[name] = val
    return ret

def load_helper_cls(project_name, params):
    cls_name = project_name.title() + 'CoverageHelper'
    cls_name = cls_name.replace('-', '_')
    try:
        cls = getattr(report_helper, cls_name)
        # TODO: add some params in class
        return cls(params)
    except:
        raise('Cannot find helper class in '
              'gen_report/report_helper.py, '
              'please add new class named %s' % cls_name)

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

        params = load_settings(obj.project)
        base_url = params['base_url']
        base_dir = params['base_dir']

        gs = prepare_gsmgr(obj.project)

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

            if gs:
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
        gs = prepare_gsmgr(obj.project)
        if gs:
            gs.search_update_by_dict({'Id': obj.id},
                                     {'Coverage Report': 'Fail to generate report'})

@task(base=CoverageReportCB)
def gen_coverage_report(obj_id, output_dir):
    shutil.rmtree(output_dir, True)
    # TODO: Ensuring a task is only executed one at a time
    obj = CoverageFile.objects.get(id=obj_id)
    if not obj.project:
        raise Exception('Not support CoverageFile without project')
    params = load_settings(obj.project)
    helper = load_helper_cls(obj.project.name, params)
    with helper.prepare_env(obj.version):
        helper.gen_report(obj.coveragefile.path, output_dir)

class MergeCoverageReportCB(CallbackTask):
    def on_success(self, retval, task_id, args, kwargs):
        super(MergeCoverageReportCB, self).on_success(retval, task_id, args, kwargs)
        if len(args) > 2:
            obj_ids, output_dir, mobj_id = args
        else:
            obj_ids, output_dir = args
            mobj_id = None

        objs = [CoverageFile.objects.get(id=obj_id) for obj_id in obj_ids]
        # TODO: need check if all have one project ?
        obj = objs[0]

        params = load_settings(obj.project)
        base_url = params['base_url']
        base_dir = params['base_dir']

        gs = prepare_gsmgr(obj.project, sheet=1)

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

            if cr.tracefile:
                old_tracefile = cr.tracefile.path
            cr.save_tracefile('/tmp/merge.tracefile')
            cr.save()

            if gs:
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
                os.unlink(old_tracefile)

        except Exception as detail:
            logger.error('Fail to finish successed work: %s' % detail)
            if not mobj_id:
                cr.delete()
            else:
                if old_path and cr.path != old_path:
                    shutil.rmtree(cr.path, True)
                    shutil.move(old_path, cr.path)
                if old_tracefile and cr.tracefile and cr.tracefile.path != old_tracefile:
                    cr.tracefile.delete(save=False)
                    cr.save_tracefile(old_tracefile)
                    os.unlink(old_tracefile)
                for obj in objs:
                    cr.coverage_files.remove(obj)


@task(base=MergeCoverageReportCB)
def merge_coverage_report(obj_ids, output_dir, merge_id=None):
    only_version = None
    coverage_files = []
    shutil.rmtree(output_dir, True)
    tmp_tracefile = '/tmp/merge.tracefile'

    if merge_id:
        obj = CoverageReport.objects.get(id=merge_id)
        ext_obj_ids = [i.id for i in obj.coverage_files.all()]
        if set(ext_obj_ids) & set(obj_ids):
            raise Exception("Found unexpected merge request, %s already "
                            "been merged in CoverageReport obj (id %d)" %
                            (str(list(set(ext_obj_ids) & set(obj_ids))), merge_id))

        only_version = '.'.join(obj.version.split('.')[:-1])
        if not obj.tracefile:
            coverage_files.extend([i.coveragefile.path for i in obj.coverage_files.all()])
        else:
            coverage_files.append(obj.tracefile.path)

    #TODO: support convert report
    for obj_id in obj_ids:
        obj = CoverageFile.objects.get(id=obj_id)
        coverage_files.append(obj.coveragefile.path)
        if only_version:
            if only_version != '.'.join(obj.version.split('.')[:-1]):
                raise Exception('Not support merge different coverage: %s != %s',
                                only_version, '.'.join(obj.version.split('.')[:-1]))
        else:
            only_version = '.'.join(obj.version.split('.')[:-1])

    if not obj:
        return

    # TODO: check have the same project
    if not obj.project:
        raise Exception('Not support CoverageFile without project')
    params = load_settings(obj.project)
    helper = load_helper_cls(obj.project.name, params)
    with helper.prepare_env(obj.version):
        helper.merge_tracefile(coverage_files, tmp_tracefile)
        helper.gen_report(tmp_tracefile, output_dir)

@task(base=MergeCoverageReportCB)
def merge_convert_coverage_report(obj_ids, output_dir, merge_id):
    tgt_version = None
    coverage_files = []
    tmp_coverage_files = []
    shutil.rmtree(output_dir, True)
    tmp_tracefile = '/tmp/merge.tracefile'

    obj = CoverageReport.objects.get(id=merge_id)
    ext_obj_ids = [i.id for i in obj.coverage_files.all()]
    if set(ext_obj_ids) & set(obj_ids):
        raise Exception("Found unexpected merge request, %s already "
                        "been merged in CoverageReport obj (id %d)" %
                        (str(list(set(ext_obj_ids) & set(obj_ids))), merge_id))

    tgt_version = '.'.join(obj.version.split('.')[:-1])
    if not obj.tracefile:
        coverage_files.extend([i.coveragefile.path for i in obj.coverage_files.all()])
    else:
        coverage_files.append(obj.tracefile.path)

    if not obj.project:
        raise Exception('Not support CoverageReport without project')
    params = load_settings(obj.project)
    helper = load_helper_cls(obj.project.name, params)

    try:
        for obj_id in obj_ids:
            tmp_obj = CoverageFile.objects.get(id=obj_id)
            if tgt_version != '.'.join(tmp_obj.version.split('.')[:-1]):
                tmp_tracefile = helper.convert_tracefile(tmp_obj.version,
                                                         obj.version,
                                                         tmp_obj.coveragefile.path)
                coverage_files.append(tmp_tracefile)
                tmp_coverage_files.append(tmp_tracefile)
            else:
                coverage_files.append(tmp_obj.coveragefile.path)

        with helper.prepare_env(obj.version):
            helper.merge_tracefile(coverage_files, tmp_tracefile)
            helper.gen_report(tmp_tracefile, output_dir)
    finally:
        for trace_file in tmp_coverage_files:
            if os.path.exists(trace_file):
                os.unlink(trace_file)

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
            if not new_objs:
                continue
            merge_coverage_report.delay([i.id for i in new_objs], '/tmp/tmpdir', obj.id)

    def _rescan_table_internal(project):
        objs = CoverageFile.objects.filter(project=project)
        gs = prepare_gsmgr(project)
        if gs:
            table = gs.get_all_values()
            _check_obj(objs, table, gs)

        objs = CoverageReport.objects.filter(project=project)
        gs = prepare_gsmgr(project, sheet=1)
        if gs:
            table = gs.get_all_values()
            _check_obj(objs, table, gs)
            _update_merge_report(objs)

    for project in Project.objects.all():
        _rescan_table_internal(project)
    #_rescan_table_internal(None)
