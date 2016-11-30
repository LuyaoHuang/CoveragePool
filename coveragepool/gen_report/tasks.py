from __future__ import absolute_import, unicode_literals
from celery import shared_task
from celery.decorators import task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task
def first_test():
    logger.info("Hello!")
    return 1
