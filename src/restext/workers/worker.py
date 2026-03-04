from arq import cron
from arq.connections import RedisSettings

from restext.config import settings
from restext.workers.tasks import crawl_source, check_stale_sources


class WorkerSettings:
    functions = [crawl_source]
    cron_jobs = [
        cron(check_stale_sources, minute={0, 15, 30, 45}),  # every 15 minutes
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
